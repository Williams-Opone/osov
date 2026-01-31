# project/extensions.py
from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail
from flask_wtf import CSRFProtect
from authlib.integrations.flask_client import OAuth
# __init__.py
from flask_login import LoginManager






# Initialize them here, but don't bind to app yet
login_manager = LoginManager()
db = SQLAlchemy()
csrf = CSRFProtect()
oauth = OAuth()
mail = Mail()