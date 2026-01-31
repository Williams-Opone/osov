
from flask import render_template, redirect, url_for, flash, request,Response,stream_with_context,make_response
from flask_login import login_user, current_user, logout_user
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from werkzeug.security import check_password_hash
from datetime import datetime, date, timedelta
from flask_mail import Message
import csv
import io
from . import mail

from flask import render_template,Blueprint,request,flash,redirect,url_for,session,current_app

from .extension import db,login_manager

from . import oauth

from sqlalchemy import func, desc

from flask_login import login_user, login_required,current_user

import cloudinary.uploader 

from .model import Event,NewsletterSubscriber,UserRole,User,PartnerApplication,Donation,Story,Campaign,SiteConfig,MentorshipApplication,VolunteerApplication,ApplicationStatus


admin_route = Blueprint('admin', __name__)




@admin_route.route('/admin/login/google')
def admingoogle_login():
    # Define the callback URL (Must match exactly what is in Google Cloud Console)
    redirect_uri = url_for('admin.admingoogle_callback', _external=True)
    return oauth.google.authorize_redirect(redirect_uri)

# --- 2. HANDLE CALLBACK ---
@admin_route.route('/admin/auth/callback')
def admingoogle_callback():
    try:
        # A. Exchange code for token
        token = oauth.google.authorize_access_token()
        
        # B. Fetch User Info explicitly (More reliable than token.get)
        user_info = oauth.google.userinfo()
        
    except Exception as e:
        print(f"Google Auth Error: {e}") # Check your console for this if it fails
        flash("Google Login failed. Please try again.", "danger")
        return redirect(url_for('admin.adminsignin'))

    if not user_info:
        flash("Could not fetch user details from Google.", "danger")
        return redirect(url_for('admin.adminsignin'))

    # C. Extract Email
    user_email = user_info.get('email')

    # D. Check Database
    existing_user = User.query.filter_by(email=user_email).first()

    # E. Define Access Rules
    allowed_roles = [UserRole.ADMIN, UserRole.MODERATOR]

    if existing_user:
        # F. Role Verification
        if existing_user.role in allowed_roles:
            
            # --- SUCCESS! ---
            login_user(existing_user)
            session.permanent = True  # Keep them logged in
            
            flash(f'Welcome to the Dashboard, {existing_user.first_name}.', 'success')
            
            # Force redirect to dashboard (Ignore 'next' for now to fix the bug)
            return redirect(url_for('admin.dashboard'))
        
        else:
            # User exists, but has wrong role
            flash('Access Denied. Admin/Moderator privileges required.', 'danger')
            return redirect(url_for('admin.adminsignin'))
            
    else:
        # Account does not exist
        flash('Access Denied. No Admin account found for this email.', 'danger')
        return redirect(url_for('admin.adminsignin'))    


@admin_route.route('/asignin', methods=['GET', 'POST'])
def adminsignin():
    # 1. Redirect if already logged in (Admin OR Moderator)
    if current_user.is_authenticated:
        if current_user.role in [UserRole.ADMIN, UserRole.MODERATOR]:
            return redirect(url_for('admin.dashboard'))
        else:
            # If a normal user tries to access this page, log them out or show error
            flash("You do not have permission to view this page.", "warning")

    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        user = User.query.filter_by(email=email).first()

        # 2. Verify Creds & Role
        if user and user.password_hash and check_password_hash(user.password_hash, password):
            
            # Allow both Admins and Moderators
            if user.role in [UserRole.ADMIN, UserRole.MODERATOR]:
                login_user(user)
                flash('Login Successful.', 'success')
                
                next_page = request.args.get('next')
                return redirect(next_page or url_for('admin.dashboard'))
            else:
                flash('Access Denied: Insufficient Privileges.', 'danger')
        else:
            flash('Invalid Email or Password.', 'danger')

    return render_template('admin/adminsignin.html')


@admin_route.route('/admin/dashboard')
@login_required
def dashboard():
    # --- 1. SECURITY CHECK (Priority #1) ---
    # Strictly enforce Admin or Moderator access before calculating stats
    if current_user.role not in [UserRole.ADMIN, UserRole.MODERATOR]:
        flash("Unauthorized access.", "warning")
        return redirect(url_for('admin.adminsignin'))

    # --- 2. GATHER STATISTICS ---
    total_users_count = User.query.count()
    
    # Calculate start of today for daily users
    today_start = datetime.combine(date.today(), datetime.min.time())
    daily_users_count = User.query.filter(User.last_login >= today_start).count()
    
    # Count pending partners (Case insensitive check)
    pending_partners_count = PartnerApplication.query.filter(PartnerApplication.status.ilike('pending')).count()
    
    # Total funds raised
    total_funds = db.session.query(func.sum(Donation.amount)).filter(Donation.status == 'Success').scalar() or 0.0

    # --- 3. PAGINATION & VIEW ALL LOGIC ---
    view_mode = request.args.get('view') 
    page = request.args.get('page', 1, type=int)
    per_page = 4 
    
    users_query = User.query.order_by(desc(User.created_at))

    if view_mode == 'all':
        # Fetch everyone (No pagination)
        users = users_query.all()
        pagination = None 
    else:
        # Standard Pagination
        pagination = users_query.paginate(page=page, per_page=per_page)
        users = pagination.items

    # --- 4. RENDER TEMPLATE ---
    return render_template('admin/admindashboard.html',
                           total_users=total_users_count,
                           daily_users=daily_users_count,
                           pending_partners=pending_partners_count,
                           total_funds=total_funds,
                           pagination=pagination,
                           users=users,
                           view_mode=view_mode,
                           active_page='dashboard', # Keeps the sidebar highlighted
                           now=datetime.utcnow())

 

@admin_route.route('/manage-stories', methods=['GET', 'POST'])
@login_required
def manage_stories():

    # PART 0: THE "LAZY CRON" (Auto-Publish Check)
    # =========================================================
    # 1. Get current time (UTC)
    now = datetime.utcnow()
    
    # 2. Find stories that are 'Scheduled' BUT their time has passed
    overdue_stories = Story.query.filter(
        Story.status == 'Scheduled', 
        Story.scheduled_for <= now
    ).all()

    # 3. Flip them to 'Published' automatically
    if overdue_stories:
        count = 0
        for story in overdue_stories:
            story.status = 'Published'
            count += 1
        
        db.session.commit()
        flash(f'{count} scheduled stor(ies) just went live!', 'success')

    if request.method == 'POST':
        try:
            story_id = request.form.get('story_id')
            # --- 1. HANDLE IMAGE UPLOAD ---
            image_url = request.form.get('existing_image_url') # Keep old image by default
            
            # Check if a NEW file was uploaded
            if 'image_file' in request.files:
                file = request.files['image_file']
                if file.filename != '':
                    # Upload to Cloudinary
                    upload_result = cloudinary.uploader.upload(file)
                    # Get the secure URL (https://...)
                    image_url = upload_result['secure_url']

            # --- 2. HANDLE STATUS & SCHEDULING ---
            status = request.form.get('status')
            scheduled_for = None
            
            # Logic: If 'Scheduled', read the HIDDEN UTC field
            if status == 'Scheduled':
                utc_date_str = request.form.get('utc_scheduled_for') # <--- LOOK HERE
                
                if utc_date_str:
                    # It is already UTC from JavaScript, just save it!
                    scheduled_for = datetime.strptime(utc_date_str, '%Y-%m-%dT%H:%M')
            
            # Note: For 'Published', we don't set a future date.
            # (The rest of your code using 'scheduled_for' below works fine with this)

            # --- 3. CREATE OR UPDATE ---
            if story_id:
                # Update Existing
                story = Story.query.get_or_404(story_id)
                story.title = request.form.get('title')
                story.summary = request.form.get('summary')
                story.content = request.form.get('content')
                story.image_url = image_url # Save the Cloudinary Link
                story.status = status
                story.scheduled_for = scheduled_for
                flash('Story updated successfully!', 'success')
            else:
                # Create New
                new_story = Story(
                    title=request.form.get('title'),
                    slug=request.form.get('title').lower().strip().replace(' ', '-'),
                    summary=request.form.get('summary'),
                    content=request.form.get('content'),
                    image_url=image_url, # Save the Cloudinary Link
                    status=status,
                    scheduled_for=scheduled_for,
                    author_id=current_user.id
                )
                db.session.add(new_story)
                flash('Story created successfully!', 'success')

            db.session.commit()
            return redirect(url_for('admin.manage_stories'))

        except Exception as e:
            db.session.rollback()
            flash(f"Error: {str(e)}", "danger")
            
        return redirect(url_for('admin.manage_stories'))

    # =========================================================
    # PART 2: FETCH DATA FOR DISPLAY (The Table & Filters)
    # =========================================================
    
    # 1. Get Filters from URL (e.g., ?status=Published&page=2)
    status_filter = request.args.get('status', 'All')
    author_filter = request.args.get('author_id', type=int)
    page = request.args.get('page', 1, type=int)
    
    # 2. Start the Query
    query = Story.query

    # 3. Apply Filters
    if status_filter != 'All':
        query = query.filter(Story.status == status_filter)
    
    if author_filter:
        query = query.filter(Story.author_id == author_filter)

    # 4. Get Counts for the Tabs (All, Published, Drafts...)
    counts = {
        'All': Story.query.count(),
        'Published': Story.query.filter_by(status='Published').count(),
        'Draft': Story.query.filter_by(status='Draft').count(), # Changed key to 'Draft' to match DB value for simplicity, or keep 'Drafts' key and fix query.
        'Scheduled': Story.query.filter_by(status='Scheduled').count()
    }

    # 5. Get Authors for the Dropdown
    authors = User.query.all()

    # 6. Pagination (Show 9 stories per page)
    # Order by 'updated_at' descending (newest edits first)
    pagination = query.order_by(desc(Story.updated_at)).paginate(page=page, per_page=9)
    stories = pagination.items

    return render_template('admin/adminmanagestories.html', 
                           stories=stories, 
                           pagination=pagination,
                           counts=counts,
                           current_status=status_filter,
                           current_author=author_filter,
                           authors=authors,active_page='stories')

@admin_route.route('/story/delete/<int:story_id>', methods=['POST'])
@login_required
def delete_story(story_id):
    story = Story.query.get_or_404(story_id)
    db.session.delete(story)
    db.session.commit()
    flash('Story deleted.', 'success')
    return redirect(url_for('admin.manage_stories'))

# --- PUBLISH ROUTE ---
@admin_route.route('/story/publish/<int:story_id>')
@login_required
def publish_story(story_id):
    story = Story.query.get_or_404(story_id)
    story.status = 'Published'
    db.session.commit()
    flash('Story is now live!', 'success')
    return redirect(url_for('admin.manage_stories'))

# Example logic for sending (Do not put this in a public route!)
def send_mass_newsletter(subject, body_html):
    # 1. Get all ACTIVE subscribers
    subscribers = NewsletterSubscriber.query.filter_by(is_active=True).all()
    
    # 2. Extract emails
    # note: Flask-Mail usually sends to one at a time or BCC. 
    # For mass email, using BCC is safer to hide user emails from each other.
    recipient_list = [sub.email for sub in subscribers]

    msg = Message(subject,
                  sender="info@ourstoryourvoice.org",
                  bcc=recipient_list) # Use BCC!
    msg.html = body_html
    mail.send(msg)

@admin_route.route('/manage-events', methods=['GET', 'POST'])
@login_required
def manage_events():
    if request.method == 'POST':
        try:
            event_id = request.form.get('event_id')
            
            # 1. Image Logic (Safe handling)
            image_url = request.form.get('existing_image_url')
            if 'image_file' in request.files:
                file = request.files['image_file']
                if file.filename != '':
                    upload = cloudinary.uploader.upload(file)
                    image_url = upload['secure_url']
            
            # 2. Date Logic (Fix: Don't wipe date if hidden field is empty on edit)
            utc_str = request.form.get('utc_date_time')
            event_date = None
            if utc_str:
                event_date = datetime.strptime(utc_str, '%Y-%m-%dT%H:%M')

            # 3. Create or Update
            if event_id:
                # --- UPDATE ---
                event = Event.query.get_or_404(event_id)
                event.title = request.form.get('title')
                event.description = request.form.get('description')
                event.location = request.form.get('location')
                event.capacity = request.form.get('capacity') or 0 # Default to 0 if empty
                event.status = request.form.get('status')
                event.image_url = image_url
                
                # Only update date if the user actually picked a new one (utc_str exists)
                if event_date: 
                    event.date_time = event_date
                
                flash('Event updated successfully!', 'success')
            else:
                # --- CREATE ---
                # For new events, we require a date
                if not event_date:
                    flash('Please select a date/time for the new event.', 'warning')
                    return redirect(url_for('admin.manage_events'))

                new_event = Event(
                    title=request.form.get('title'),
                    description=request.form.get('description'),
                    date_time=event_date,
                    location=request.form.get('location'),
                    capacity=request.form.get('capacity') or 0,
                    status=request.form.get('status'),
                    image_url=image_url
                )
                db.session.add(new_event)
                flash('Event created successfully!', 'success')

            db.session.commit()
            return redirect(url_for('admin.manage_events'))

        except Exception as e:
            db.session.rollback()
            # It's better to print the specific error to your console for debugging
            print(f"Error saving event: {e}") 
            flash(f"Error: {str(e)}", "danger")
            return redirect(url_for('admin.manage_events'))

    # GET REQUEST
    events = Event.query.order_by(Event.date_time.desc()).all()
    return render_template('admin/adminevent.html', events=events,active_page='events')

# --- DELETE ROUTE ---
@admin_route.route('/event/delete/<int:event_id>', methods=['POST'])
@login_required
def delete_event(event_id):
    event = Event.query.get_or_404(event_id)
    db.session.delete(event)
    db.session.commit()
    flash('Event deleted.', 'success')
    return redirect(url_for('admin.manage_events'))

@admin_route.route('/admin/fundraising')
@login_required
def fundraising():
    # --- 1. KEY METRICS (Existing Logic) ---
    total_raised = db.session.query(func.sum(Donation.amount))\
        .filter(Donation.status == 'Success').scalar() or 0.0

    monthly_recurring = db.session.query(func.sum(Donation.amount))\
        .filter(Donation.status == 'Success', Donation.frequency == 'monthly').scalar() or 0.0

    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    avg_donation = db.session.query(func.avg(Donation.amount))\
        .filter(Donation.status == 'Success', Donation.created_at >= thirty_days_ago).scalar() or 0.0

    # --- 2. ACTIVE CAMPAIGNS (NEW DYNAMIC LOGIC) ---
    # Fetch all campaigns where is_active is True
    active_campaigns = Campaign.query.filter_by(is_active=True).order_by(Campaign.created_at.desc()).all()

    # --- 3. RECENT TRANSACTIONS (Existing Logic) ---
    recent_donations = Donation.query.filter_by(status='Success')\
        .order_by(Donation.created_at.desc())\
        .limit(3).all()

    return render_template('admin/adminfundraising.html', 
                           total_raised=total_raised,
                           monthly_recurring=monthly_recurring,active_page='fundraising',
                           avg_donation=avg_donation,
                           recent_donations=recent_donations,
                           active_campaigns=active_campaigns) # Pass the list here

# --- CSV EXPORT ROUTE ---
@admin_route.route('/admin/fundraising/export_csv')
@login_required
def export_donations_csv():
    # Fetch ALL successful donations
    donations = Donation.query.filter_by(status='Success').order_by(Donation.created_at.desc()).all()

    def generate():
        data = io.StringIO()
        w = csv.writer(data)

        # Write Header
        w.writerow(('Date', 'Donor Name', 'Email', 'Amount', 'Currency', 'Frequency', 'Reference'))
        yield data.getvalue()
        data.seek(0)
        data.truncate(0)

        for d in donations:
            # Logic to find name/email (User vs Guest)
            if d.user_id:
                # Assuming User model has first_name/last_name/email
                # Use "d.user" relationship if it exists, otherwise query or handle gracefully
                name = f"User ID {d.user_id}" # Placeholder if relationship not loaded
                email = "Registered User"
                # If you have d.user relationship:
                # name = f"{d.user.first_name} {d.user.last_name}"
                # email = d.user.email
            else:
                name = d.guest_name or "Anonymous"
                email = d.guest_email or "No Email"

            w.writerow((
                d.created_at.strftime("%Y-%m-%d %H:%M"),
                name,
                email,
                f"{d.amount:.2f}",
                d.currency,
                d.frequency,
                d.reference
            ))
            yield data.getvalue()
            data.seek(0)
            data.truncate(0)

    response = Response(stream_with_context(generate()), mimetype='text/csv')
    response.headers.set('Content-Disposition', 'attachment', filename='osov_donations_report.csv')
    return response
@admin_route.route('/admin/approvals')
@login_required
def approvals():
    # --- 1. STATISTICS ---
    stats = {
        'partners_applied': PartnerApplication.query.count(),
        'partners_approved': PartnerApplication.query.filter_by(status='Approved').count(),
        'partners_rejected': PartnerApplication.query.filter_by(status='Rejected').count(),
        'volunteers_applied': VolunteerApplication.query.count(),
        'volunteers_approved': VolunteerApplication.query.filter_by(status=ApplicationStatus.APPROVED).count(),
        'mentorship_count': MentorshipApplication.query.count(),
    }

    # --- 2. PENDING TABLES ---
    page = request.args.get('page', 1, type=int)
    partners_pagination = PartnerApplication.query.filter_by(status='Pending')\
        .order_by(PartnerApplication.created_at.desc())\
        .paginate(page=page, per_page=5)

    v_page = request.args.get('v_page', 1, type=int)
    volunteers_pagination = VolunteerApplication.query.filter_by(status=ApplicationStatus.PENDING)\
        .order_by(VolunteerApplication.created_at.desc())\
        .paginate(page=v_page, per_page=5)

    # --- 3. ACTIVE PARTNERS (For Deletion/Management) ---
    # We fetch all currently approved partners so you can end their contracts
    active_partners = PartnerApplication.query.filter_by(status='Approved')\
        .order_by(PartnerApplication.created_at.desc()).all()

    # --- 4. RECENT LISTS ---
    recent_mentors = MentorshipApplication.query.order_by(MentorshipApplication.created_at.desc()).limit(5).all()
    recent_approved = PartnerApplication.query.filter_by(status='Approved').order_by(PartnerApplication.created_at.desc()).limit(5).all()

    return render_template('admin/admin_approvals.html',
                           active_page='approvals',
                           stats=stats,
                           partners_pagination=partners_pagination,
                           volunteers_pagination=volunteers_pagination,
                           active_partners=active_partners, # NEW
                           recent_mentors=recent_mentors,
                           recent_approved=recent_approved)


def send_approval_email(user_email, user_name, role_type):
    try:
        msg = Message(
            subject=f"Application Approved: {role_type}",
            sender=current_app.config['MAIL_USERNAME'],
            recipients=[user_email]
        )
        msg.html = f"""
        <div style="font-family: Arial, sans-serif; padding: 20px; border: 1px solid #eee;">
            <h2 style="color: #166534;">Congratulations, {user_name}!</h2>
            <p>We are thrilled to inform you that your application for <strong>{role_type}</strong> with <em>Our Story Our Voice</em> has been <strong>APPROVED</strong>.</p>
            <p>Our team will be in touch shortly with the next steps.</p>
            <br>
            <p>Welcome to the community!</p>
        </div>
        """
        mail.send(msg)
    except Exception as e:
        print(f"Email Error: {e}")

# --- NEW ACTION ROUTE: PROCESS VOLUNTEERS ---
@admin_route.route('/admin/volunteer/<int:id>/<action>')
@login_required
def process_volunteer(id, action):
    application = VolunteerApplication.query.get_or_404(id)
    
    if action == 'approve':
        application.status = ApplicationStatus.APPROVED
        flash(f'Approved volunteer: {application.user.first_name}', 'success')
        # Send Email
        send_approval_email(application.user.email, application.user.first_name, "Volunteer")
        
    elif action == 'reject':
        application.status = ApplicationStatus.REJECTED
        flash(f'Rejected volunteer: {application.user.first_name}', 'warning')
    
    db.session.commit()
    return redirect(url_for('admin_route.approvals'))

# --- PROCESS PARTNER ---
@admin_route.route('/admin/partner/<int:id>/<action>')
@login_required
def process_partner(id, action):
    application = PartnerApplication.query.get_or_404(id)
    
    if action == 'approve':
        application.status = 'Approved'
        flash(f'Approved partnership with {application.org_name}', 'success')
        # Send Email
        send_approval_email(application.user.email, application.user.first_name, "Partnership")
        
    elif action == 'reject':
        application.status = 'Rejected'
        flash(f'Rejected partnership with {application.org_name}', 'warning')
    
    db.session.commit()
    return redirect(url_for('admin_route.approvals'))

# --- NEW: END PARTNER CONTRACT (Soft Delete) ---
@admin_route.route('/admin/partner/<int:id>/end_contract')
@login_required
def end_partner_contract(id):
    application = PartnerApplication.query.get_or_404(id)
    
    # We change status to 'Archived' instead of deleting
    application.status = 'Archived' 
    db.session.commit()
    
    flash(f'Contract ended for {application.org_name}. Moved to archives.', 'info')
    return redirect(url_for('admin_route.approvals'))

def generate_csv_response(headers, rows, filename):
    # 1. Create an in-memory string buffer
    si = io.StringIO()
    cw = csv.writer(si)
    
    # 2. Write the header row
    cw.writerow(headers)
    
    # 3. Write the data rows
    cw.writerows(rows)
    
    # 4. Create the response object
    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = f"attachment; filename={filename}.csv"
    output.headers["Content-type"] = "text/csv"
    return output


@admin_route.route('/admin/export/partners')
@login_required
def export_partners():
    partners = PartnerApplication.query.all()
    
    headers = ['ID', 'Organization', 'Representative', 'Email', 'Type', 'Website', 'Status', 'Date Applied']
    rows = []
    
    for p in partners:
        rows.append([
            p.id,
            p.org_name,
            f"{p.user.first_name} {p.user.last_name}",
            p.user.email,
            p.partnership_type,
            p.website or 'N/A',
            p.status,
            p.created_at.strftime('%Y-%m-%d')
        ])
        
    return generate_csv_response(headers, rows, "osov_partners_export")

@admin_route.route('/admin/export/volunteers')
@login_required
def export_volunteers():
    volunteers = VolunteerApplication.query.all()
    
    headers = ['ID', 'Name', 'Email', 'Phone', 'Country', 'Age Group', 'Motivation', 'Status', 'Date Applied']
    rows = []
    
    for v in volunteers:
        is_minor = "Under 18" if v.is_under_18 else "Adult"
        rows.append([
            v.id,
            f"{v.user.first_name} {v.user.last_name}",
            v.user.email,
            v.phone or 'N/A',
            v.country,
            is_minor,
            v.motivation,
            v.status.value, # Enum value
            v.created_at.strftime('%Y-%m-%d')
        ])
        
    return generate_csv_response(headers, rows, "osov_volunteers_export")

@admin_route.route('/admin/export/mentorships')
@login_required
def export_mentorships():
    mentors = MentorshipApplication.query.all()
    
    headers = ['ID', 'Applicant Name', 'Email', 'Program Track', 'Mentee Name', 'School', 'Interest', 'Status', 'Date Applied']
    rows = []
    
    for m in mentors:
        mentee_name = f"{m.child_first_name} {m.child_last_name}" if m.child_first_name else "N/A"
        rows.append([
            m.id,
            f"{m.user.first_name} {m.user.last_name}",
            m.user.email,
            m.program_track,
            mentee_name,
            m.school_name or 'N/A',
            m.vocational_interest or 'N/A',
            m.status,
            m.created_at.strftime('%Y-%m-%d')
        ])
        
    return generate_csv_response(headers, rows, "osov_mentorships_export")

@admin_route.route('/admin/campaigns', methods=['GET', 'POST'])
@login_required
def manage_campaigns():
    # --- HANDLE FORM SUBMISSION ---
    if request.method == 'POST':
        try:
            campaign_id = request.form.get('campaign_id')
            
            # Create/Edit Logic
            if campaign_id:
                # UPDATE
                campaign = Campaign.query.get_or_404(campaign_id)
                campaign.title = request.form.get('title')
                campaign.goal_amount = float(request.form.get('goal_amount') or 0)
                campaign.description = request.form.get('description')
                # Checkbox handling: if 'is_active' is not in form, it means unchecked (False)
                campaign.is_active = 'is_active' in request.form 
                
                flash('Campaign updated successfully!', 'success')
            else:
                # CREATE
                new_campaign = Campaign(
                    title=request.form.get('title'),
                    goal_amount=float(request.form.get('goal_amount') or 0),
                    description=request.form.get('description'),
                    is_active='is_active' in request.form
                )
                db.session.add(new_campaign)
                flash('Campaign created successfully!', 'success')

            db.session.commit()
            return redirect(url_for('admin.manage_campaigns'))

        except Exception as e:
            db.session.rollback()
            flash(f"Error: {str(e)}", "danger")
            return redirect(url_for('admin.manage_campaigns'))

    # --- HANDLE DISPLAY (GET) ---
    # Sort active first, then by newest
    campaigns = Campaign.query.order_by(Campaign.is_active.desc(), Campaign.created_at.desc()).all()
    
    return render_template('admin/admin_campaigns.html', campaigns=campaigns,active_page='campaigns')

# --- DELETE CAMPAIGN ---
@admin_route.route('/admin/campaigns/delete/<int:campaign_id>', methods=['POST'])
@login_required
def delete_campaign(campaign_id):
    campaign = Campaign.query.get_or_404(campaign_id)
    
    # Check if it has money attached
    if campaign.donations:
        flash('Cannot delete campaign with existing donations. Archive it instead.', 'warning')
    else:
        db.session.delete(campaign)
        db.session.commit()
        flash('Campaign deleted.', 'success')
        
    return redirect(url_for('admin.manage_campaigns'))

@admin_route.route('/admin/settings', methods=['GET', 'POST'])
@login_required
def settings():
    # --- 1. HANDLE POST REQUESTS (Actions) ---
    if request.method == 'POST':
        action = request.form.get('action')

        # A. UPDATE PROFILE
        if action == 'update_profile':
            current_user.first_name = request.form.get('first_name')
            current_user.last_name = request.form.get('last_name')
            current_user.email = request.form.get('email')
            db.session.commit()
            flash('Profile updated successfully.', 'success')

        # B. CHANGE PASSWORD
        elif action == 'change_password':
            current_pw = request.form.get('current_password')
            new_pw = request.form.get('new_password')
            confirm_pw = request.form.get('confirm_password')

            if not current_user.check_password(current_pw):
                flash('Incorrect current password.', 'danger')
            elif new_pw != confirm_pw:
                flash('New passwords do not match.', 'danger')
            else:
                current_user.set_password(new_pw)
                db.session.commit()
                flash('Password changed successfully.', 'success')

        # C. TOGGLE MAINTENANCE (Admin Only)
        elif action == 'toggle_maintenance' and current_user.role == UserRole.ADMIN:
            mode = 'true' if 'maintenance_mode' in request.form else 'false'
            
            config = SiteConfig.query.filter_by(key='maintenance_mode').first()
            if not config:
                config = SiteConfig(key='maintenance_mode', value=mode)
                db.session.add(config)
            else:
                config.value = mode
            
            db.session.commit()
            status = "ON" if mode == 'true' else "OFF"
            flash(f'Maintenance Mode is now {status}.', 'warning')

        # D. UPDATE SUPPORT EMAIL (New Code)
        elif action == 'update_support_email' and current_user.role == UserRole.ADMIN:
            new_email = request.form.get('support_email')
            
            config = SiteConfig.query.filter_by(key='support_email').first()
            if not config:
                config = SiteConfig(key='support_email', value=new_email)
                db.session.add(config)
            else:
                config.value = new_email
            
            db.session.commit()
            flash('Public contact email updated.', 'success')

        # E. INVITE MEMBER (New Functional Code)
        elif action == 'invite_member' and current_user.role == UserRole.ADMIN:
            email_to_invite = request.form.get('invite_email')
            
            # 1. Find user in DB
            user = User.query.filter_by(email=email_to_invite).first()
            
            if user:
                if user.role == UserRole.MODERATOR or user.role == UserRole.ADMIN:
                    flash(f'{user.first_name} is already a team member.', 'warning')
                else:
                    # 2. Upgrade Role
                    user.role = UserRole.MODERATOR
                    db.session.commit()
                    
                    # 3. Send Email
                    try:
                        send_moderator_email(user.email, user.first_name)
                        flash(f'Success! {user.first_name} is now a Moderator and has been notified.', 'success')
                    except Exception as e:
                        flash(f'{user.first_name} is promoted, but email failed: {str(e)}', 'warning')
            else:
                flash(f'User with email {email_to_invite} not found. They must register first.', 'danger')

        return redirect(url_for('admin.settings'))

    # --- 2. GET DATA FOR DISPLAY ---
    
    # Team: Get Admins and Moderators
    team_members = User.query.filter(User.role.in_([UserRole.ADMIN, UserRole.MODERATOR])).all()
    
    # Maintenance Status
    m_config = SiteConfig.query.filter_by(key='maintenance_mode').first()
    is_maintenance = m_config.value == 'true' if m_config else False

    # Support Email Status (New Code)
    s_config = SiteConfig.query.filter_by(key='support_email').first()
    public_email = s_config.value if s_config else "info@ourstoryourvoice.org"

    # Device Info
    ua = request.user_agent
    device_info = {
        'browser': ua.browser.capitalize() if ua.browser else "Unknown Browser",
        'platform': ua.platform.capitalize() if ua.platform else "Unknown OS",
        'string': ua.string
    }

    return render_template('admin/adminsettings.html', 
                           team_members=team_members,active_page='settings',
                           is_maintenance=is_maintenance,
                           public_email=public_email, # Pass this new variable
                           device_info=device_info)

def send_moderator_email(to_email, first_name):
    # EMAIL CONFIGURATION (Replace with your actual details)
    SMTP_SERVER = "smtp.gmail.com" # or "smtp.sendgrid.net"
    SMTP_PORT = 587
    SENDER_EMAIL = "admin@ourstoryourvoice.ca" 
    SENDER_PASSWORD = "your_app_password_here" # Use an App Password if using Gmail

    subject = "You've been promoted to Moderator at OSOV"
    body = f"""
    Hello {first_name},

    Great news! You have been promoted to a Moderator role on the Our Story Our Voice platform.
    
    Please login here to access your new tools:
    https://ourstoryourvoice.ca/login

    Welcome to the team!
    - OSOV Admin
    """

    msg = MIMEMultipart()
    msg['From'] = SENDER_EMAIL
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.send_message(msg)
        server.quit()
    except Exception as e:
        print(f"Email failed: {e}") # Log error to console

# --- HELPER ROUTE: PROMOTE TO MODERATOR ---
@admin_route.route('/admin/promote/<int:user_id>')
@login_required
def promote_user(user_id):
    if current_user.role != UserRole.ADMIN:
        flash('Permission denied.', 'danger')
        return redirect(url_for('admin.settings'))
        
    user = User.query.get_or_404(user_id)
    if user.role == UserRole.USER:
        user.role = UserRole.MODERATOR
        db.session.commit()
        flash(f'{user.first_name} is now a Moderator.', 'success')
    
    return redirect(url_for('admin.settings'))


@admin_route.route('/logouts')
def logouts():
    # --- THIS LINE DESTROYS THE SESSION ---
    logout_user()
    # --------------------------------------
    
    flash('You have been logged out successfully.', 'info')
    return redirect(url_for('admin.adminsignin'))
    