import os
import cloudinary
from flask import Flask, request, render_template, flash
from dotenv import load_dotenv
from flask_login import current_user
from werkzeug.middleware.proxy_fix import ProxyFix
from .extension import db, csrf, oauth, mail, login_manager
from . import config
from .model import UserRole

load_dotenv()

def create_app():
    app = Flask(__name__)
    app.config.from_object(config)

    # Fix the URI
    uri = os.environ.get('SQLALCHEMY_DATABASE_URI', "")
    
    if uri.startswith("mysql://"):
        uri = uri.replace("mysql://", "mysql+pymysql://", 1)
    elif uri.startswith("mysql+mysqlconnector://"):
        uri = uri.replace("mysql+mysqlconnector://", "mysql+pymysql://", 1)
        
    if '?' in uri:
        uri = uri.split('?')[0]
        
    app.config['SQLALCHEMY_DATABASE_URI'] = uri

    # TiDB SSL Config
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        "connect_args": {
            "ssl": {
                "ca": "/etc/ssl/certs/ca-certificates.crt",
                "check_hostname": True
            }
        }
    }

    # Vercel Proxy Setup
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    # Initialize Extensions
    csrf.init_app(app)
    db.init_app(app)
    mail.init_app(app)
    login_manager.init_app(app)
    oauth.init_app(app)

    # Secret Key
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev_default_key')

    # Cloudinary Config
    cloudinary.config(
        cloud_name=os.environ.get('cloud_name'), 
        api_key=os.environ.get('api_key'), 
        api_secret=os.environ.get('api_secret')
    )

    # Login Manager Setup
    from flask import redirect, url_for 
    
    @login_manager.unauthorized_handler
    def handle_needs_login():
        if request.endpoint and request.endpoint.startswith('admin.'):
            return redirect(url_for('admin.adminsignin')) 
        next_url = request.path 
        flash("Please log in to access this page.", "error")
        return redirect(url_for('main.signin', next=next_url))

    from .model import User

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Google OAuth Registration with PKCE (fixes the state mismatch error on Vercel)
    oauth.register(
    name='google',
    client_id=os.environ.get('GOOGLE_CLIENT_ID'),
    client_secret=os.environ.get('GOOGLE_CLIENT_SECRET'),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={
        'scope': 'openid email profile',
    }
    )

    # Register Blueprints
    from .userroute import main_routes
    app.register_blueprint(main_routes)    

    from .adminroute import admin_route
    app.register_blueprint(admin_route)    

    # Error Handlers
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
    if request.path.startswith('/static'):
        return None
    if request.path.startswith('/admin') or request.path.startswith('/auth'):
        return None
    from .model import SiteConfig
    is_down = SiteConfig.is_maintenance_mode()
    if is_down:
        if not current_user.is_authenticated:
            return render_template('error/maintenance.html'), 503
        if current_user.role == UserRole.USER:
            return render_template('error/maintenance.html'), 503

from project import config, userroute, adminroute, model, extension