import os
import cloudinary
from flask import Flask,request,render_template,flash
from dotenv import load_dotenv
from flask_login import current_user
# 1. Import extensions (Removed 'cloudinary' from this list)
from .extension import db, csrf, oauth, mail, login_manager
from . import config
from .model import UserRole

load_dotenv()

def create_app():
    app = Flask(__name__)
    
    app.config.from_object(config)
    
    # Initialize Extensions
    csrf.init_app(app)
    db.init_app(app)
    mail.init_app(app)
    login_manager.init_app(app)
    oauth.init_app(app)

    # Mail Config
    
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev_default_key')
    

    # 2. CONFIGURE CLOUDINARY HERE (And nowhere else)
    # Ensure these keys match your .env file exactly!
    cloudinary.config(
        cloud_name = os.environ.get('cloud_name'), 
        api_key = os.environ.get('api_key'), 
        api_secret = os.environ.get('api_secret')
    )

    # Login Manager Setup
    from flask import request, redirect, url_for 
    
    @login_manager.unauthorized_handler
    def handle_needs_login():
        if request.endpoint and request.endpoint.startswith('admin.'):
            return redirect(url_for('admin.adminsignin')) 
        
        # FIX: Pass the current page (request.path) as the 'next' argument
        flash("Please log in to access this page.", "error")
        return redirect(url_for('main.signin', next=request.path))

    from .model import User

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Google OAuth Registration
    oauth.register(
        name='google',
        client_id=app.config.get('GOOGLE_CLIENT_ID'),         
        client_secret=app.config.get('GOOGLE_CLIENT_SECRET'), 
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={'scope': 'openid email profile'}
    )

    # Register Blueprints
    from .userroute import main_routes
    app.register_blueprint(main_routes)    

    from .adminroute import admin_route
    app.register_blueprint(admin_route)    

    # Register Error Handlers
    @app.errorhandler(404)
    def page_not_found(e):
        return render_template('error/404.html'), 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        return render_template('error/405.html'), 405
    
    @app.errorhandler(503)
    def maintenance_error(error):
        return render_template('error/maintenance.html'), 503

    @app.errorhandler(500)
    def internal_server_error(e):
        return render_template('error/500.html'), 500

    return app

app = create_app()

@app.before_request
def check_maintenance():
    # 1. Allow Static Files (CSS/JS/Images)
    if request.path.startswith('/static'):
        return None
        
    # 2. Allow Admin & Auth Routes (So you don't lock yourself out!)
    if request.path.startswith('/admin') or request.path.startswith('/auth'):
        return None
        
    # 3. Check Database for Maintenance Mode
    from .model import SiteConfig
    is_down = SiteConfig.is_maintenance_mode()
    
    # 4. If ON, block access
    if is_down:
        # If user is NOT logged in -> Show Maintenance
        if not current_user.is_authenticated:
            return render_template('error/maintenance.html'), 503
            
        # OPTIONAL: If user IS logged in but is NOT staff -> Show Maintenance
        # (Remove this block if you want normal users to stay logged in during maintenance)
        if current_user.role == UserRole.USER:
             return render_template('error/maintenance.html'), 503


from project import config, userroute,adminroute,model,extension