import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get('CAT_DATA_DIR', os.path.join(BASE_DIR, 'data'))
UPLOADS_DIR = os.path.join(DATA_DIR, 'uploads')
os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

SECRET_KEY = os.environ.get('CAT_SECRET_KEY', os.urandom(32).hex())
SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', f'sqlite:///{os.path.join(DATA_DIR, "catmes.db")}')
SQLALCHEMY_TRACK_MODIFICATIONS = False

RATE_LIMIT = 0.5
MAX_XP = 99999
UPLOAD_MAX_SIZE = 5 * 1024 * 1024
ALLOWED_EXTENSIONS = {'png', 'jpeg', 'jpg', 'gif', 'webp'}

ROLES = {'krembovan': 'owner'}
SITE_URL = 'https://catmes.ru'
