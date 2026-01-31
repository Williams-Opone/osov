import os
from dotenv import load_dotenv
import stripe

load_dotenv() # Load variables from .env if it exists


# config.py
GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET')

SECRET_KEY = os.environ.get('SECRET_KEY')

SQLALCHEMY_DATABASE_URI = 'mysql+mysqlconnector://root:@localhost/osov'

SQLALCHEMY_TRACK_MODIFICATIONS = False


MAIL_SERVER = "smtp.hostinger.com"
MAIL_PORT = 465  # Switch to 465 (SSL)
MAIL_USE_SSL = True  # Enable SSL
MAIL_USE_TLS = False # Disable TLS
MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
MAIL_DEFAULT_SENDER = os.environ.get('MAIL_USERNAME')

stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')




