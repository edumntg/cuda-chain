import os
from dotenv import load_dotenv

load_dotenv() # Load environment variables from .env file if present

SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-for-jwt") # Should be strong and from env
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
