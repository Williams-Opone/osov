from flask_login import UserMixin
from .extension import db
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from enum import Enum
from werkzeug.security import generate_password_hash,check_password_hash



# --- 1. ENUMS FOR ROLES & STATUS ---
class UserRole(Enum):
    USER = "user"
    MODERATOR = "moderator"
    ADMIN = "admin"

class ApplicationStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"

# --- 2. USER MANAGEMENT (Auth & Settings) ---
class User(db.Model,UserMixin):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=True)
    
    # Defines if they are User, Moderator, or Admin
    role = db.Column(db.Enum(UserRole), default=UserRole.USER, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    donations = db.relationship('Donation', backref='donor', lazy=True)
    rsvps = db.relationship('EventRSVP', backref='attendee', lazy=True)
    
    volunteer_application = db.relationship('VolunteerApplication', back_populates='user', uselist=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role == UserRole.ADMIN

# --- NEW MODEL FOR SITE CONFIGURATION ---
class SiteConfig(db.Model):
    __tablename__ = 'site_config'
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False) # e.g., 'maintenance_mode'
    value = db.Column(db.String(255), default="false") # 'true' or 'false'

    @staticmethod
    def is_maintenance_mode():
        config = SiteConfig.query.filter_by(key='maintenance_mode').first()
        return config and config.value == 'true'

# --- 3. STORIES (Admin/Mod Only) ---
class Story(db.Model):
    __tablename__ = 'stories'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(200), unique=True, nullable=False)
    
    # Content
    summary = db.Column(db.String(300), nullable=False)
    content = db.Column(db.Text, nullable=False)
    image_url = db.Column(db.String(500))
    scheduled_for = db.Column(db.DateTime, nullable=True)
    # Metadata
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    category = db.Column(db.String(50), default='General')
    
    
    # --- NEW FIELDS FOR IMAGE FEATURES ---
    # Status options: 'Draft', 'Published', 'Scheduled'
    status = db.Column(db.String(20), default='Draft', nullable=False) 
    views = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    author = db.relationship('User', backref='stories')

    # Helper to calculate "2 hours ago" etc.
    def time_ago(self):
        now = datetime.utcnow()
        diff = now - self.updated_at
        if diff.days > 0:
            return f"{diff.days} days ago"
        seconds = diff.seconds
        if seconds < 60:
            return "Just now"
        if seconds < 3600:
            return f"{seconds // 60} minutes ago"
        return f"{seconds // 3600} hours ago"

# --- 4. COMMUNITY Q&A (Admin/Mod answers, Users view) ---
class CommunityQA(db.Model):
    __tablename__ = 'community_qa'
    
    id = db.Column(db.Integer, primary_key=True)
    question = db.Column(db.String(500), nullable=False) # The topic/question
    answer = db.Column(db.Text, nullable=False) # The detailed answer
    
    # Only Admins/Mods can create these entries
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# --- 5. EVENTS & RSVP ---
class Event(db.Model):
    __tablename__ = 'events'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    
    # We use this for the actual event time
    date_time = db.Column(db.DateTime, nullable=False) 
    
    location = db.Column(db.String(200))
    capacity = db.Column(db.Integer)
    image_url = db.Column(db.String(500)) # Removed default for cleaner logic
    
    # --- NEW FIELD FOR DRAFTS ---
    status = db.Column(db.String(20), default='Draft') # 'Draft' or 'Published'
    
    rsvps = db.relationship('EventRSVP', backref='event', lazy=True, cascade="all, delete-orphan")
class EventRSVP(db.Model):
    __tablename__ = 'event_rsvps'
    
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id'), nullable=False)
    
    # User Link (Optional, if they are logged in)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    
    # Guest Info
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    
    # --- NEW FIELD FOR TICKET SYSTEM ---
    # Stores the unique 8-char code (e.g., "A1B2C3D4")
    ticket_id = db.Column(db.String(20), unique=True, nullable=True) 
    
    # Extra Form Data
    company = db.Column(db.String(100))
    how_heard = db.Column(db.String(100))
    
    rsvp_date = db.Column(db.DateTime, default=datetime.utcnow)
# --- 6. VOLUNTEERING & MENTORSHIP ---
class VolunteerApplication(db.Model):
    """
    The Private Application Form.
    Only Admins see this.
    """
    __tablename__ = 'volunteer_applications'

    id = db.Column(db.Integer, primary_key=True)
    
    # RELATIONAL LINK: Links this application to a specific User account
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # LEGAL & DEMOGRAPHICS (From Option A)
    # We don't need 'email' or 'name' here because we can get them from user_id
    phone = db.Column(db.String(20))
    country = db.Column(db.String(50) , nullable = False)
    dob = db.Column(db.Date, nullable=False)
    is_under_18 = db.Column(db.Boolean, default=False)
    parent_consent = db.Column(db.Boolean, default=False)

    # SUBJECTIVE DATA
    motivation = db.Column(db.Text)
    skills = db.Column(db.Text)

    # STATUS TRACKING
    status = db.Column(db.Enum(ApplicationStatus), default=ApplicationStatus.PENDING)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationship to access user info easily (e.g., application.user.email)    
    user = db.relationship('User', back_populates='volunteer_application')

class VolunteerProfile(db.Model):
    """
    The Public Profile.
    This is created ONLY after the application is Approved.
    """
    __tablename__ = 'volunteer_profiles'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # PUBLIC INFO
    role_title = db.Column(db.String(100)) # e.g. "Mentor", "Community Lead"
    public_bio = db.Column(db.Text)        # A shorter version of their motivation
    photo_url = db.Column(db.String(500))
    
    is_active = db.Column(db.Boolean, default=True)
    
    user = db.relationship('User', backref=db.backref('volunteer_profile', uselist=False))

class MentorshipApplication(db.Model):
    __tablename__ = 'mentorship_applications'
    
    id = db.Column(db.Integer, primary_key=True)
    # This links to the account filling the form (The Parent or Adult Applicant)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    program_track = db.Column(db.String(50), nullable=False)
    
    # --- NEW FIELDS FOR YOUTH TRACK ---
    # The name of the child receiving mentorship
    child_first_name = db.Column(db.String(50)) 
    child_last_name = db.Column(db.String(50))
    
    # The name of the parent/guardian (Explicitly stated for consent)
    guardian_name = db.Column(db.String(100))
    
    # ... keep your existing fields (grade_level, school_name, parent_email, etc.) ...
    grade_level = db.Column(db.String(20))
    school_name = db.Column(db.String(100))
    parent_email = db.Column(db.String(120))
    
    # ... keep IDP fields ...
    vocational_interest = db.Column(db.String(100))
    business_idea = db.Column(db.Text)
    
    goals = db.Column(db.Text)
    status = db.Column(db.String(20), default='Pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref='mentorship_apps')

class PartnerApplication(db.Model):
    __tablename__ = 'partner_applications'
    
    id = db.Column(db.Integer, primary_key=True)
    # The user submitting this (The Representative)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Organization Info
    org_name = db.Column(db.String(150), nullable=False)
    org_type = db.Column(db.String(50)) # School, NGO, Corporate
    website = db.Column(db.String(200))
    
    # Partnership Details
    # Options: 'Sponsorship', 'Venue', 'Skills_Training', 'Internship_Placement'
    partnership_type = db.Column(db.String(50), nullable=False)
    
    # Specific Offer (e.g., "We can donate 5 laptops" or "We need 2 interns")
    proposal_details = db.Column(db.Text, nullable=False)
    
    # Status: Pending -> Contacted -> Vetted -> Active -> Rejected
    status = db.Column(db.String(20), default='Pending')
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref='partner_apps')
# --- 7. FUNDRAISING & DONATIONS ---

class Donation(db.Model):
    __tablename__ = 'donations'
     
    id = db.Column(db.Integer, primary_key=True)
    
    # Who donated? (Nullable because guests can donate)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    guest_email = db.Column(db.String(120)) # If not logged in
    guest_name = db.Column(db.String(100))
    
    # Financials
    amount = db.Column(db.Float, nullable=False) # e.g. 50.00
    
    # UPDATED: Changed default to CAD since you are operating in Canada now
    currency = db.Column(db.String(3), default="CAD") 
    
    # --- NEW FIELDS FOR RECURRING PAYMENTS ---
    # Stores 'onetime' or 'monthly'
    frequency = db.Column(db.String(20), default='onetime', nullable=False)
    
    # Stores the Stripe Subscription ID (e.g., 'sub_1Mg7...') 
    # Only populated if frequency == 'monthly'
    stripe_subscription_id = db.Column(db.String(100), nullable=True)
    
    # Stores the Stripe Customer ID (e.g., 'cus_9sF...')
    # Good for linking future payments to the same person
    stripe_customer_id = db.Column(db.String(100), nullable=True)
    # -----------------------------------------

    # Technicals
    # This stores the Session ID (cs_test_...) initially
    reference = db.Column(db.String(100), unique=True, nullable=False) 
    status = db.Column(db.String(20), default='Pending') # Pending, Success, Failed, Cancelled
    
    # Campaign (Optional)
    campaign_id = db.Column(db.Integer, db.ForeignKey('campaigns.id'), nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# models.py

class Campaign(db.Model):
    __tablename__ = 'campaigns'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    goal_amount = db.Column(db.Float, default=0.0) # e.g. 50000.00
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationship: One Campaign has Many Donations
    # cascade="all, delete-orphan" isn't used here because we don't want to 
    # delete money records if a campaign is deleted. We just set their campaign_id to NULL.
    donations = db.relationship('Donation', backref='campaign_rel', lazy=True)

    # Helper to calculate total raised dynamically
    def total_raised(self):
        # Sum all successful donations linked to this campaign
        total = sum(d.amount for d in self.donations if d.status == 'Success')
        return total

    # --- REPLACE THE OLD progress_percent WITH THIS ---
    def progress_percent(self):
        raised = self.total_raised()
        if self.goal_amount > 0:
            percent = int((raised / self.goal_amount) * 100)
            # We return the raw percent (e.g. 120) so the text says "120% Funded"
            # The HTML 'overflow-hidden' we added prevents the visual bar from breaking.
            return percent 
        return 0

# --- 8. NEWSLETTER ---
class NewsletterSubscriber(db.Model):
    __tablename__ = 'newsletter_subscribers'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    
    # We use this instead of deleting the row so we don't annoy them if they accidentally sign up again
    is_active = db.Column(db.Boolean, default=True) 
    
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Subscriber {self.email}>'