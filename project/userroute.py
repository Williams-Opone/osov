import os
from dotenv import load_dotenv # Import this
import urllib.parse
# Load variables from .env file
import smtplib
import uuid
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import re
import stripe 
from flask_login import login_user, login_required,current_user

from datetime import date, datetime
from sqlalchemy import desc,distinct
from flask_mail import Message
from . import mail # Import the mail instance we created above
from itsdangerous import URLSafeTimedSerializer

from flask import render_template,Blueprint,url_for,redirect,session,request,flash,current_app,abort
from werkzeug.security import generate_password_hash , check_password_hash
from .model import User,VolunteerApplication,MentorshipApplication,PartnerApplication,Event,EventRSVP,Story,Donation,NewsletterSubscriber,Campaign
from .extension import db


from . import oauth  # <--- IMPORT OAUTH FROM YOUR __INIT__ FILE

s = URLSafeTimedSerializer(os.getenv('SECRET_KEY'))

main_routes = Blueprint('main', __name__)


@main_routes.errorhandler(503)
def maintenance_error(error):
    return render_template('error/maintenance.html'), 503

@main_routes.errorhandler(404)
def page_not_found(e):
    return render_template('error/404.html'), 404

@main_routes.errorhandler(405)
def method_not_allowed(e):
    return render_template('error/405.html'), 405
@main_routes.errorhandler(500)
def internal_server_error(e):
    # It's good practice to have a generic 500 page too
    return render_template('error/500.html'), 500

@main_routes.route('/login/google')
def google_login():
    # 1. SAVE THE GOAL
    # We look for 'next' in the URL (e.g., /login/google?next=/volunteer)
    next_page = request.args.get('next')
    if next_page:
        session['next_url'] = next_page

    # 2. PROCEED TO GOOGLE
    redirect_uri = url_for('main.google_callback', _external=True)
    return oauth.google.authorize_redirect(redirect_uri)

@main_routes.route('/auth/callback')
def google_callback():
    # 1. Get info from Google
    token = oauth.google.authorize_access_token()
    user_info = token.get('userinfo')
    
    if not user_info:
        return redirect(url_for('main.google_login'))

    user_email = user_info['email']

    # 2. CHECK DATABASE: Does this user exist?
    existing_user = User.query.filter_by(email=user_email).first()

    if existing_user:
        # --- SCENARIO A: RETURNING USER ---
        # FIX: Use Flask-Login
        login_user(existing_user)
        
        # Optional: Update profile pic if needed here
        
    else:
        # --- SCENARIO B: NEW USER ---
        # Safe name extraction
        first_name = user_info.get('given_name')
        last_name = user_info.get('family_name')
        
        if not first_name:
            name_parts = user_info.get('name', '').split(' ', 1)
            first_name = name_parts[0]
            last_name = name_parts[1] if len(name_parts) > 1 else ''

        new_user = User(
            first_name=first_name,
            last_name=last_name,
            email=user_email
            # password_hash is None because they use Google
        )

        db.session.add(new_user)
        db.session.commit() 
        
        # FIX: Use Flask-Login
        login_user(new_user)
        print("New user created and logged in via Google.")

    # 3. Handle Redirects (Go to 'next' if it exists, otherwise Home)
    next_url = session.pop('next_url', None)
    
    if next_url and next_url.startswith('/'):
        return redirect(next_url)
        
    return redirect(url_for('main.index'))


@main_routes.route('/',methods = ['GET','POST'])
def index():
    # Debug line: Remove the filter to prove you have 3 events
    upcoming_events = Event.query.order_by(Event.date_time.desc()).limit(3).all()
    # explicit join condition
    stories = Story.query.join(User).order_by(Story.created_at.desc()).limit(10).all()
    return render_template('user/index.html',stories=stories,events=upcoming_events)

@main_routes.route('/about', methods = ['POST','GET'])
def about():
    return render_template('user/about.html')

# @main_routes.route('/stories')
# def viewstory():
#     return render_template('user/viewstory.html')

@main_routes.route('/stories')
def stories():
    # 1. Check if a category is selected in the URL (e.g. /stories?category=Youth)
    selected_category = request.args.get('category')
    
    # 2. Start the query
    query = Story.query.filter_by(status='Published') # Only show published ones
    
    # 3. Apply Filter if selected
    if selected_category and selected_category != 'All Stories':
        query = query.filter(Story.category == selected_category)
    
    # 4. Fetch the Results
    recent_stories = query.order_by(Story.created_at.desc()).limit(9).all()

    # 5. Fetch ALL unique categories from the DB (for the buttons)
    # This creates a list like ['General', 'Youth Success', 'Immigrant Journeys']
    categories_query = db.session.query(distinct(Story.category)).filter(Story.status == 'Published').all()
    # Clean up the list (remove tuples)
    categories = [c[0] for c in categories_query if c[0]]

    return render_template(
        'user/stories.html', 
        stories=recent_stories, 
        categories=categories,
        current_category=selected_category
    )

@main_routes.route('/story/<slug>')
def story_detail(slug):
    # 1. Fetch the story
    current_story = Story.query.filter_by(slug=slug).first_or_404()

    # 2. Security Check: Only show if Published
    # (Optional: You can remove this if you want admins to see drafts via this link)
    if current_story.status != 'Published':
        abort(404)

    # 3. SMART VIEW COUNTER
    # Create a unique session key for this specific story
    view_key = f'viewed_story_{current_story.id}'

    # Check if this user has already viewed this story in this session
    if view_key not in session:
        current_story.views += 1
        db.session.commit()
        session[view_key] = True  # Mark as viewed

    # 4. Fetch "More Stories" for the recommendation section
    more_stories = Story.query.filter(
        Story.id != current_story.id, 
        Story.status == 'Published'  # Ensure recommendations are also published!
    ).order_by(Story.created_at.desc()).limit(4).all()

    # 5. Render the template
    return render_template('user/story_detail.html', story=current_story, more_stories=more_stories)



# ... imports ...

@main_routes.route('/contact', methods=['GET', 'POST'])
def contact_us():
    if request.method == 'POST':
        # 1. Get Data
        f_name = request.form.get('first_name')
        l_name = request.form.get('last_name')
        user_email = request.form.get('email')
        topic = request.form.get('topic')
        msg_content = request.form.get('message')

        system_email = current_app.config['MAIL_USERNAME']

        # --- EMAIL 1: TO ADMIN (The HTML Layout) ---
        admin_msg = Message(
            subject=f"New Inquiry: {topic}", 
            sender=system_email, 
            recipients=['info@ourstoryourvoice.org', 'oponeboboola@gmail.com'], # Sends to Info AND You
            reply_to=user_email
        )

        admin_msg.html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body {{ font-family: Arial, sans-serif; background-color: #f3f4f6; color: #111827; }}
                .container {{ max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 16px; overflow: hidden; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
                .header {{ background-color: #ffffff; padding: 30px; text-align: center; border-bottom: 1px solid #eee; }}
                .content {{ padding: 40px; }}
                .label {{ font-size: 11px; font-weight: 700; text-transform: uppercase; color: #9CA3AF; display: block; margin-top: 20px; }}
                .value {{ font-size: 16px; font-weight: 500; color: #333; }}
                .msg-box {{ background-color: #f9fafb; padding: 20px; border-left: 4px solid #4F46E5; margin-top: 10px; font-style: italic; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>New Website Inquiry 🚀</h2>
                </div>
                <div class="content">
                    <span class="label">From</span>
                    <div class="value">{f_name} {l_name}</div>

                    <span class="label">Email</span>
                    <div class="value"><a href="mailto:{user_email}">{user_email}</a></div>

                    <span class="label">Topic</span>
                    <div class="value">{topic}</div>

                    <span class="label">Message</span>
                    <div class="msg-box">"{msg_content}"</div>
                    
                    <br>
                    
                </div>
            </div>
        </body>
        </html>
        """

        # --- EMAIL 2: TO USER (Confirmation) ---
        user_msg = Message(
            subject=f"We received your message - Our Story Our Voice",
            sender=system_email,
            recipients=[user_email] # Send to the user
        )
        
        user_msg.body = f"""
        Hi {f_name},

        Thank you for contacting Our Story Our Voice. 
        
        We have received your message regarding "{topic}" and our team will review it shortly. We aim to respond within 2-3 business days.

        Best regards,
        The OSOV Team
        www.ourstoryourvoice.org
        """

        # 4. Attempt to Send Both
        try:
            mail.send(admin_msg) # Send to you
            mail.send(user_msg)  # Send to them
            
            flash('Message sent successfully! Check your inbox for a confirmation.', 'success')
            return redirect(url_for('main.contact_us'))
            
        except Exception as e:
            print(f"❌ EMAIL FAILED: {str(e)}")
            flash('There was an issue sending your message. Please try again later.', 'error')
            return redirect(url_for('main.contact_us'))

    return render_template('user/contact.html')

stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')

@main_routes.route('/campaigns')
def campaign_list():
    # Fetch all active campaigns from the DB
    campaigns = Campaign.query.filter_by(is_active=True).order_by(Campaign.created_at.desc()).all()
    return render_template('user/campaign_list.html', campaigns=campaigns)

# --- ROUTE 2: THE DONATION PAGE (Handles both General & Specific) ---
@main_routes.route('/donate', methods=['GET', 'POST'])
@main_routes.route('/donate/<int:campaign_id>', methods=['GET', 'POST'])
def donate(campaign_id=None):
    
    # 1. Determine Context (General vs. Specific Campaign)
    selected_campaign = None
    if campaign_id:
        selected_campaign = Campaign.query.get_or_404(campaign_id)

    # --- NEW: Check for Active Subscription ---
    active_subscription = None
    if current_user.is_authenticated:
        active_subscription = Donation.query.filter_by(
            user_id=current_user.id,
            frequency='monthly',
            status='Active' # We only want active plans
        ).first()
    # ------------------------------------------

    # 2. HANDLE POST (Processing the payment)
    if request.method == 'POST':
        try:
            amount = float(request.form.get('amount'))
            frequency = request.form.get('frequency') 
            
            # Auth Logic
            if current_user.is_authenticated:
                email = current_user.email
                name = f"{current_user.first_name} {current_user.last_name}"
                user_id = current_user.id
            else:
                email = request.form.get('guest_email')
                name = request.form.get('guest_name')
                user_id = None

            # Dynamic Product Name
            product_name = "Donation to Our Story Our Voice"
            if selected_campaign:
                product_name = f"Donation: {selected_campaign.title}"

            # --- STRIPE LOGIC ---
            price_data = {
                'currency': 'cad',
                'product_data': {
                    'name': product_name,
                    'description': f'{frequency.capitalize()} contribution',
                },
                'unit_amount': int(amount * 100), 
            }

            if frequency == 'monthly':
                checkout_mode = 'subscription'
                price_data['recurring'] = {'interval': 'month'}
            else:
                checkout_mode = 'payment'

            # Create Session
            checkout_session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{'price_data': price_data, 'quantity': 1}],
                mode=checkout_mode,
                customer_email=email,
                metadata={
                    'user_id': user_id,
                    'guest_name': name,
                    'is_donation': 'true',
                    'frequency': frequency,
                    'campaign_id': campaign_id if campaign_id else '' 
                },
                success_url=url_for('main.donation_success', _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
                cancel_url=url_for('main.donate', campaign_id=campaign_id, _external=True),
            )

            # Save "Pending" Donation to DB
            new_donation = Donation(
                user_id=user_id,
                guest_email=email,
                guest_name=name,
                amount=amount,
                currency='CAD',
                frequency=frequency,
                reference=checkout_session.id,
                status='Pending',
                campaign_id=campaign_id 
            )
            db.session.add(new_donation)
            db.session.commit()

            return redirect(checkout_session.url, code=303)

        except Exception as e:
            print(f"Stripe Error: {e}")
            flash('Payment gateway connection failed.', 'error')
            return redirect(url_for('main.donate', campaign_id=campaign_id))

    # 3. HANDLE GET (Rendering the page)
    # UPDATED: Passing 'active_sub' to the template
    return render_template('user/donatenow.html', 
                           campaign=selected_campaign, 
                           active_sub=active_subscription)


@main_routes.route('/cancel-subscription/<int:donation_id>', methods=['POST'])
@login_required
def cancel_subscription(donation_id):
    donation = Donation.query.get_or_404(donation_id)
    
    # Security Check
    if donation.user_id != current_user.id:
        flash('Unauthorized', 'error')
        return redirect(url_for('main.donate'))

    try:
        # Cancel at Stripe
        if donation.stripe_subscription_id:
            stripe.Subscription.modify(
                donation.stripe_subscription_id,
                cancel_at_period_end=True
            )
        
        # Update DB
        donation.status = 'Cancelled'
        db.session.commit()
        flash('Subscription cancelled successfully.', 'success')
        
    except Exception as e:
        print(f"Stripe Error: {e}")
        flash('Error cancelling subscription.', 'error')

    # UPDATED: Redirects back to the donate page so they see the change immediately
    return redirect(url_for('main.donate'))

@main_routes.route('/donation/success')
def donation_success():
    session_id = request.args.get('session_id')
    
    if not session_id:
        return redirect(url_for('main.donate'))

    try:
        # Retrieve the session from Stripe
        session = stripe.checkout.Session.retrieve(session_id)
        
        # Update the database
        donation = Donation.query.filter_by(reference=session_id).first()
        
        if donation:
            # --- START OF UPDATED LOGIC ---
            
            # Check if Stripe created a subscription ID
            sub_id = session.get('subscription')

            if sub_id:
                # CASE 1: It is a Recurring Subscription
                donation.status = 'Active'  # Use 'Active' for subscriptions
                donation.stripe_subscription_id = sub_id
                donation.stripe_customer_id = session.get('customer')
                donation.frequency = 'monthly' # Ensure consistency
            else:
                # CASE 2: It is a One-Time Donation
                donation.status = 'Success'

            # --- END OF UPDATED LOGIC ---

            db.session.commit()
            
            return render_template('user/donation_success.html', amount=donation.amount)
            
    except Exception as e:
        print(f"Error verifying donation: {e}")
        flash('Error verifying donation.', 'error')
        return redirect(url_for('main.donate'))

    return redirect(url_for('main.index'))

@main_routes.route('/history')
@login_required
def donation_history():
    # Fetch all donations for the current user, newest first
    donations = Donation.query.filter_by(user_id=current_user.id)\
        .order_by(Donation.created_at.desc())\
        .all()
    
    return render_template('user/donation_history.html', donations=donations)

@main_routes.route('/mentorship')
def mentorship():

    return render_template('user/mentorship.html')

@main_routes.route('/mentorship/apply', methods=['GET', 'POST'])
@login_required
def apply_mentorship():
    # Check if they already applied
    existing_app = MentorshipApplication.query.filter_by(user_id=current_user.id).first()
    if existing_app:
        return render_template('user/mentorship_status.html', app=existing_app)

    if request.method == 'POST':
        track = request.form.get('program_track')
        
        # Base Application
        new_app = MentorshipApplication(
            user_id=current_user.id,
            program_track=track,
            goals=request.form.get('goals')
        )
        
        # CONDITIONAL LOGIC: Only save relevant fields based on track
        if track == 'youth_school':
            new_app.child_first_name = request.form.get('child_fname')
            new_app.child_last_name = request.form.get('child_lname')
            new_app.guardian_name = request.form.get('guardian_name')
            
            new_app.grade_level = request.form.get('grade_level')
            new_app.school_name = request.form.get('school_name')
            new_app.parent_email = request.form.get('parent_email')
            
        elif track == 'idp_reintegration':
            new_app.vocational_interest = request.form.get('vocational_interest')
            new_app.business_idea = request.form.get('business_idea')

        try:
            db.session.add(new_app)
            db.session.commit()
            flash('Application received! We will review it shortly.', 'success')
            return redirect(url_for('main.mentorship_success')) # Create this route next
        except Exception as e:
            db.session.rollback()
            flash('Error submitting application.', 'error')

    return render_template('user/mentorship_form.html')

@main_routes.route('/partner/apply', methods=['GET', 'POST'])
@login_required
def apply_partner():
    # 1. DUPLICATE CHECK: Has this user already applied?
    existing_app = PartnerApplication.query.filter_by(user_id=current_user.id).first()
    
    if existing_app:
        # If they already applied, show them their status (reuse the mentorship status logic or a new page)
        # For now, let's redirect to a status page specific for partners
        return render_template('user/partner_status.html', app=existing_app)

    if request.method == 'POST':
        # 2. Get Form Data
        org_name = request.form.get('org_name')
        org_type = request.form.get('org_type')
        website = request.form.get('website')
        p_type = request.form.get('partnership_type')
        proposal = request.form.get('proposal')

        # 3. Validation
        if not all([org_name, org_type, p_type, proposal]):
            flash('Please fill in all required fields.', 'error')
            return render_template('user/partner_form.html')

        # 4. Save to DB
        new_partner = PartnerApplication(
            user_id=current_user.id,
            org_name=org_name,
            org_type=org_type,
            website=website,
            partnership_type=p_type,
            proposal_details=proposal,
            status='Pending'
        )
        
        try:
            db.session.add(new_partner)
            db.session.commit()
            
            # Generate URL *before* flashing to catch errors early
            target_url = url_for('main.partner_success') 
            
            flash('Partnership proposal received! We will contact you shortly.', 'success')
            return redirect(target_url)
            
        except Exception as e:
            db.session.rollback()
            print(f"Error: {e}") # Check your terminal, I bet it says 'BuildError'
            flash('An error occurred. Please try again.', 'error')
            return render_template('user/partner_form.html')
        
    return render_template('user/partner_form.html')
        
@main_routes.route('/partner/success')
@login_required
def partner_success():
    return render_template('user/partner_success.html')

@main_routes.route('/mentorship/status')
@login_required
def mentorship_status():
    return render_template('user/mentorship_status.html')

@main_routes.route('/mentorship/success')
@login_required
def mentorship_success():
    return render_template('user/mentorship_success.html')

@main_routes.route('/signin', methods=['GET', 'POST'])
def signin():
    # If user is already logged in, send them home immediately
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        email = request.form.get('email')
        pwd = request.form.get('pwd')

        if not email or not pwd:
            flash('Please fill in all fields', 'error')
            return render_template('user/signin.html')
        
        existing_user = User.query.filter_by(email=email).first()

        # 1. VERIFY USER AND PASSWORD (Using your Model's method)
        # Use .check_password() instead of importing check_password_hash here
        if existing_user and existing_user.password_hash and existing_user.check_password(pwd):
            
            # A. Login Success
            login_user(existing_user)
            
            # B. Handle "Next" URL
            next_page = request.args.get('next')
            if not next_page or not next_page.startswith('/'):
                next_page = url_for('main.index')
            
            return redirect(next_page)
        
        # 2. LOGIN FAILED
        flash('Invalid Email or Password', 'error')

    return render_template('user/signin.html')

@main_routes.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        user = User.query.filter_by(email=email).first()

        if user:
            # Generate a token valid for 1800 seconds (30 mins)
            print(user)
            token = s.dumps(email, salt='password-reset-salt')
            
            # Create the Link
            link = url_for('main.reset_password', token=token, _external=True)
            
            # SEND EMAIL (Or print to console for testing)
            msg = Message('Password Reset Request', sender='info@ourstoryourvoice.org', recipients=[email])
            msg.body = f'Click the link to reset your password: {link}'
            
            try:
                mail.send(msg)
                flash('Check your email for a password reset link.', 'info')
            except Exception as e:
                print(e)
                flash('Error sending email. Check console.', 'error')
                # FOR TESTING ONLY: Print link to console so you can click it
                print(f"TESTING LINK: {link}") 
        else:
            # Security: Don't tell them if the email doesn't exist to prevent fishing
            flash('If that email exists, we have sent a link.', 'info')
            
        return redirect(url_for('main.signin'))

    return render_template('user/forgot_password.html')


# ROUTE 2: THE RESET PAGE (Enter New Password)
@main_routes.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    try:
        # Verify Token (Max age 30 mins)
        email = s.loads(token, salt='password-reset-salt', max_age=1800)
    except:
        flash('The reset link is invalid or has expired.', 'error')
        return redirect(url_for('main.signin'))

    if request.method == 'POST':
        pwd = request.form.get('pwd')
        conpwd = request.form.get('conpwd')

        if pwd != conpwd:
            flash('Passwords do not match.', 'error')
            return redirect(request.url) # Reload current page

        # Update Password
        user = User.query.filter_by(email=email).first()
        user.password_hash = generate_password_hash(pwd)
        db.session.commit()

        flash('Your password has been updated! Please log in.', 'success')
        return redirect(url_for('main.signin'))

    return render_template('user/reset_password.html', token=token)

@main_routes.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        # 1. Get Data
        firstname = request.form.get('fname')
        lastname = request.form.get('lname')
        email = request.form.get('email')
        pwd = request.form.get('pwd')
        conpwd = request.form.get('conpwd')

        # 2. Basic Validation: Check for empty fields
        if not all([firstname, lastname, email, pwd, conpwd]):
            flash('Please fill in all fields', 'error')
            return render_template('user/signup.html')

        # 3. Validation: Check if passwords match
        if pwd != conpwd:
            flash('Passwords do not match', 'error')
            return render_template('user/signup.html')

        # 4. Database Check: Does email already exist?
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            flash('Email address already exists. Please Log in.', 'error')
            # Redirect to login, NOT index, and DO NOT log them in automatically
            return redirect(url_for('main.signin')) 

        # 5. Validation: Password Strength (Regex)
        # Explanation: At least 8 chars, 1 uppercase, 1 lowercase, 1 number, 1 special char
        pattern = r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,}$"
        
        if not re.match(pattern, pwd):
            flash('Password must be at least 8 characters, include an uppercase letter, a number, and a special character.', 'error')
            return render_template('user/signup.html')

        # 6. Create User
        # Hash the password properly
        hashed_password = generate_password_hash(pwd)

        new_user = User(
            first_name=firstname,
            last_name=lastname,
            email=email,
            password_hash=hashed_password
        )

        try:
            db.session.add(new_user)
            db.session.commit()
            
            # 7. Log them in immediately after signup (Standard UX)
            
            login_user(new_user)
            flash('Account created successfully!', 'success')
            # Check if there is a 'next' parameter in the URL
            next_page = request.args.get('next')

            # Security Check: Ensure it's a valid internal URL (starts with /)
            if next_page and next_page.startswith('/'):
                return redirect(next_page)
            
            return redirect(url_for('main.index'))
        
        except Exception as e:
            db.session.rollback() # CRITICAL: Undo changes if error occurs
            print(f"Database Error: {e}")
            flash('An error occurred while creating your account.', 'error')
            return render_template('user/signup.html')

    # GET Request (Show the form)
    return render_template('user/signup.html')


@main_routes.route('/volunteer/status')
@login_required
def application_status():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('main.signin'))

    # Fetch the application to show details
    application = VolunteerApplication.query.filter_by(user_id=user_id).first()
    
    # If they haven't applied yet, send them to the apply page
    if not application:
        return redirect(url_for('main.volunteer'))
        
    return render_template('user/application_status.html', application=application, current_user=User.query.get(user_id))

@main_routes.route('/volunteer/success')
@login_required
def volunteer_success():
    return render_template('user/volunteersuccess.html')

@main_routes.route('/volunteer', methods=['GET', 'POST'])
@login_required
def volunteer():
    # 1. Check for existing application
    existing_volunteer = VolunteerApplication.query.filter_by(user_id=current_user.id).first()
    
    if existing_volunteer:
        return redirect(url_for('main.application_status'))

    # 2. OPTIMIZATION: Check for existing application IMMEDIATELY
    # Do this before checking POST/GET. If they applied, kick them out nicely.
    

    # 3. Handle Form Submission
    if request.method == 'POST':
        phone = request.form.get('phone')
        country = request.form.get('country')
        dob_str = request.form.get('dob')
        motivation = request.form.get('motivation')
        skills = request.form.get('skills')
        parent_consent_checked = request.form.get('parent_consent') == 'on'

        if not all([country, dob_str, motivation, skills]):
            flash('All fields must be filled out.', 'error')
            return render_template('user/volunteer.html')

        try:
            birth_date = datetime.strptime(dob_str, '%Y-%m-%d').date()
            today = date.today()
            age = today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))
            is_minor = (age < 18)

            if is_minor and not parent_consent_checked:
                flash('Parental consent is required for volunteers under 18.', 'error')
                return render_template('user/volunteer.html')
            
            if age < 15:
                flash('You must be at least 15 years old to volunteer.', 'error')
                return render_template('user/volunteer.html')

            new_volunteer = VolunteerApplication(
                user_id=current_user.id,
                phone=phone,
                country=country,
                dob=birth_date,
                is_under_18=is_minor,
                parent_consent=parent_consent_checked,
                motivation=motivation,
                skills=skills
            )

            db.session.add(new_volunteer)
            db.session.commit()
            
            # Success!
            return redirect(url_for('main.volunteer_success'))

        except ValueError:
            flash('Invalid date format.', 'error')
        except Exception as e:
            db.session.rollback()
            print(f"Database Error: {e}")
            flash('An error occurred.', 'error')

    # 4. Render Form (Only reached if no existing app and request is GET)
    return render_template('user/volunteer.html')

@main_routes.route('/events',methods= ['GET','POST'])
def events():
    # 1. Fetch Upcoming Events (Sorted by soonest first)
    upcoming_events = Event.query.all()
    # 2. OPTIMIZATION: Get list of IDs the user has already RSVP'd to.
    # This prevents us from running a database query inside the HTML loop (N+1 problem)
    my_rsvp_ids = []
    if current_user.is_authenticated:
        # Create a simple list of integers: [1, 4, 9]
        my_rsvp_ids = [rsvp.event_id for rsvp in current_user.rsvps]

    return render_template('user/events.html', events=upcoming_events, my_rsvp_ids=my_rsvp_ids)

@main_routes.route('/event/<int:event_id>')
def event_detail(event_id):
    event = Event.query.get_or_404(event_id)
    
    # Check if user is registered (for button logic)
    is_registered = False
    if current_user.is_authenticated:
        rsvp = EventRSVP.query.filter_by(user_id=current_user.id, event_id=event_id).first()
        if rsvp:
            is_registered = True
            
    return render_template('user/event_detail.html', event=event, is_registered=is_registered)

# THE RSVP ACTION (You need this to make the button work)
@main_routes.route('/event/<int:event_id>/rsvp', methods=['POST'])
def rsvp_event(event_id):
    # 1. Get Event
    event = Event.query.get_or_404(event_id)
    
    # 2. Get Data from Form
    data = request.form
    
    # 3. Determine User vs Guest
    if current_user.is_authenticated:
        user_id = current_user.id
        email = current_user.email
        first_name = current_user.first_name
        last_name = current_user.last_name
    else:
        user_id = None
        email = data.get('email')
        first_name = data.get('first_name')
        last_name = data.get('last_name')

    # 4. Duplicate Check (Works for both Users AND Guests now)
    # Check if this email has already RSVP'd for this specific event
    existing_rsvp = EventRSVP.query.filter_by(event_id=event_id).filter(
        (EventRSVP.user_id == user_id) if user_id else (EventRSVP.guest_email == email)
    ).first()

    if existing_rsvp:
        flash('You are already registered for this event.', 'info')
        # Redirect to modal with existing ticket
        return redirect(url_for('main.event_detail', event_id=event_id, rsvp_success='true', ticket_id=existing_rsvp.ticket_id))

    # 5. Generate Unique Ticket ID
    ticket_code = str(uuid.uuid4())[:8].upper()

    # 6. Save to DB
    new_rsvp = EventRSVP(
        event_id=event.id,
        user_id=user_id,
        guest_email=email,
        # Save full name for guests if needed, or split fields
        guest_name=f"{first_name} {last_name}".strip(),
        ticket_id=ticket_code,
        # Optional fields from your form
        company=data.get('company'),
        how_heard=data.get('how_heard')
    )

    try:
        db.session.add(new_rsvp)
        db.session.commit()

        # --- 7. SEND EMAIL (Hostinger Logic) ---
        try:
            msg = Message(
                subject=f"Your Ticket: {event.title}",
                recipients=[email],
                sender=current_app.config.get('MAIL_DEFAULT_SENDER') # Uses config
            )
            
            # HTML Email Body (Your nice design)
            msg.html = f"""
            <div style="font-family: sans-serif; padding: 20px; border: 1px solid #eee; max-width: 600px; margin: 0 auto;">
                <h2 style="color: #333;">You're Confirmed!</h2>
                <p>Hi {first_name}, your spot for <strong>{event.title}</strong> is reserved.</p>
                
                <div style="background: #f0fdf4; border: 1px solid #bbf7d0; padding: 15px; margin: 20px 0; border-radius: 8px; text-align: center;">
                    <p style="margin:0; font-size: 14px; color: #166534;">YOUR TICKET ID</p>
                    <p style="margin: 5px 0 0 0; font-size: 24px; font-weight: bold; letter-spacing: 2px; color: #15803d;">{ticket_code}</p>
                </div>

                <p><strong>Date:</strong> {event.date_time.strftime('%B %d, %Y at %I:%M %p')}</p>
                <p><strong>Location:</strong> {event.location}</p>
                <hr style="border: 0; border-top: 1px solid #eee;">
                <p style="font-size: 12px; color: #666;">Please show this email at the entrance.</p>
            </div>
            """
            
            mail.send(msg)
            print(f"Email sent successfully to {email}")

        except Exception as e:
            # We catch email errors so the user still gets their ticket on screen
            print(f"Email failed to send: {e}")
        # ---------------------------------------

        return redirect(url_for('main.event_detail', event_id=event_id, rsvp_success='true', ticket_id=ticket_code))

    except Exception as e:
        db.session.rollback()
        print(f"Database Error: {e}")
        flash('An error occurred while registering. Please try again.', 'error')
        return redirect(url_for('main.event_detail', event_id=event_id))    



@main_routes.route('/events/unrsvp/<int:event_id>', methods=['POST'])
@login_required
def unrsvp_event(event_id):
    # 1. Fetch Event & RSVP
    event = Event.query.get_or_404(event_id)
    rsvp = EventRSVP.query.filter_by(user_id=current_user.id, event_id=event_id).first()
    
    if rsvp:
        # 2. Capture email BEFORE deleting the record
        recipient_email = rsvp.email 
        
        try:
            # 3. Delete from DB
            db.session.delete(rsvp)
            db.session.commit()
            
            # 4. Prepare Email
            msg = Message(
                subject=f"Cancellation Confirmed: {event.title}",
                sender=current_app.config['MAIL_USERNAME'],
                recipients=[recipient_email]
            )
            
            msg.html = f"""
            <div style="font-family: Arial, sans-serif; padding: 20px; border: 1px solid #eee; border-radius: 8px;">
                <h2 style="color: #d32f2f;">Registration Cancelled</h2>
                <p>Hi {current_user.first_name},</p>
                <p>This email confirms that you have successfully <strong>cancelled your reservation</strong> for:</p>
                
                <div style="background-color: #f9fafb; padding: 15px; margin: 15px 0; border-left: 4px solid #d32f2f;">
                    <p style="margin: 0; font-weight: bold;">{event.title}</p>
                    <p style="margin: 5px 0 0 0; color: #666;">{event.date_time.strftime('%B %d, %Y')}</p>
                </div>

                <p>Your spot has been released to other attendees.</p>
                <p style="font-size: 12px; color: #888; margin-top: 20px;">The Our Story Our Voice Team</p>
            </div>
            """
            
            # 5. Send
            mail.send(msg)
            print(f"✅ Un-RSVP Email sent to {recipient_email}")
            flash('Registration cancelled successfully.', 'info')

        except Exception as e:
            # Log the error but don't crash the user
            print(f"❌ Email Failed: {e}")
            flash('Registration cancelled, but email confirmation failed.', 'warning')
            
    else:
        flash('You were not registered for this event.', 'error')
        
    return redirect(url_for('main.event_detail', event_id=event_id))




# --- Helper Function to send emails ---
def send_email_to_user(subject, recipient_email, html_body):
    """
    Sends an email using Hostinger SMTP settings stored in Environment Variables.
    """
    try:
        # 1. Load credentials from Environment Variables (Best Practice)
        # NEVER hardcode passwords in a function!
        smtp_server = os.environ.get('MAIL_SERVER', 'smtp.hostinger.com')
        smtp_port = int(os.environ.get('MAIL_PORT', 587))
        email_user = os.environ.get('MAIL_USERNAME')
        email_password = os.environ.get('MAIL_PASSWORD')
        
        # 2. Setup the MIME
        msg = MIMEMultipart()
        msg['From'] = email_user
        msg['To'] = recipient_email
        msg['Subject'] = subject
        
        # Attach the body
        msg.attach(MIMEText(html_body, 'html', 'utf-8'))

        # 3. Connect and Send
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls() 
        server.login(email_user, email_password)
        
        # Send the email
        server.sendmail(email_user, recipient_email, msg.as_string())
        
        # Close connection
        server.quit()
        
        print(f"✅ Email sent successfully to {recipient_email}")
        return True

    except Exception as e:
        # In production, use logging.error(e) instead of print
        print(f"❌ Failed to send email: {e}")
        return False

@main_routes.route('/founder')
def founder():
    return render_template('user/founder.html')

@main_routes.route('/commq&a')
def comm():
    return render_template('/user/comunityqa.html')

@main_routes.route('/termsofservice')
def TOS():
    return render_template('user/T.O.S.html')

@main_routes.route('/privacypolicy')
def privacy():
    return render_template('user/privacy.html')

@main_routes.route('/logout')
def logout():
    user  = session.get('user_id')
    session.pop('user_id', None)
    return redirect(url_for('main.index'))

