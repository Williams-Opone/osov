import os
import cloudinary
from flask import Flask,request,render_template,flash
from dotenv import load_dotenv
import json
from flask_login import current_user
from flask_session import Session
from werkzeug.middleware.proxy_fix import ProxyFix # 1. ADD THIS IMPORT
# 1. Import extensions (Removed 'cloudinary' from this list)
from .extension import db, csrf, oauth, mail, login_manager
from . import config
from .model import UserRole

load_dotenv()

def create_app():
    app = Flask(__name__)
    # 1. Load base settings (like SECRET_KEY)
    app.config.from_object(config)

    # 2. Get and Fix the URI
    # Even if config.py or Vercel Env Vars have the wrong driver, this fixes it.
    uri = os.environ.get('SQLALCHEMY_DATABASE_URI', "")
    
    if uri.startswith("mysql://"):
        uri = uri.replace("mysql://", "mysql+pymysql://", 1)
    elif uri.startswith("mysql+mysqlconnector://"):
        uri = uri.replace("mysql+mysqlconnector://", "mysql+pymysql://", 1)
        
    # Strip string-based SSL params to prevent "TypeError: argument 18 must be bool"
    if '?' in uri:
        uri = uri.split('?')[0]
        
    app.config['SQLALCHEMY_DATABASE_URI'] = uri

    # 3. Explicit PyMySQL SSL Config (The TiDB Requirement)
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        "connect_args": {
            "ssl": {
                "ca": "/etc/ssl/certs/ca-certificates.crt",
                "check_hostname": True
            }
        }
    }

    # 4. Standard Vercel Proxy Setup
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    
    
    # Initialize Extensions
    csrf.init_app(app)
    db.init_app(app)
    mail.init_app(app)
    login_manager.init_app(app)
    oauth.init_app(app)

    # Mail Config
    
    
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev_default_key')
    app.config["SESSION_TYPE"] = "sqlalchemy"
    app.config["SESSION_SQLALCHEMY"] = db
    Session(app)


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
        # 1. If they were trying to access an admin page, send them to Admin Sign-in
        if request.endpoint and request.endpoint.startswith('admin.'):
            return redirect(url_for('admin.adminsignin')) 
        
        # 2. Otherwise, capture the full path (including query params) 
        # and send them to the main Sign-in page
        next_url = request.path 
        flash("Please log in to access this page.", "error")
        return redirect(url_for('main.signin', next=next_url))

    from .model import User

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

   
    # Google OAuth Registration
    oauth.register(
    name='google',
    client_id=os.environ.get('GOOGLE_CLIENT_ID'),
    client_secret=os.environ.get('GOOGLE_CLIENT_SECRET'),
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