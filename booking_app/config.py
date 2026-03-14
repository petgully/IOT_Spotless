"""
Production Configuration for Petgully Booking App
"""
import os


class Config:
    """Base configuration."""
    
    # Flask
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    
    # Database - AWS RDS Aurora MySQL
    DB_HOST = os.environ.get('DB_HOST', 'petgully-dbserver.cmzwm2y64qh8.us-east-1.rds.amazonaws.com')
    DB_PORT = int(os.environ.get('DB_PORT', 3306))
    DB_USER = os.environ.get('DB_USER', 'spotless001')
    DB_PASSWORD = os.environ.get('DB_PASSWORD', '')
    DB_NAME = os.environ.get('DB_NAME', 'petgully_db')
    DB_SSL = os.environ.get('DB_SSL', 'true').lower() == 'true'
    
    # Google OAuth (optional)
    GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID')
    GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET')
    
    # App Settings
    DEBUG = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    

class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True
    

class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False
    
    # Ensure SECRET_KEY is set in production
    @property
    def SECRET_KEY(self):
        key = os.environ.get('SECRET_KEY')
        if not key:
            raise ValueError("SECRET_KEY environment variable must be set in production")
        return key


# Config selector
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}


def get_config():
    """Get configuration based on environment."""
    env = os.environ.get('FLASK_ENV', 'development')
    return config.get(env, config['default'])()
