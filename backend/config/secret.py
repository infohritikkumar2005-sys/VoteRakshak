# backend/config/secret.py
import os
from dotenv import load_dotenv

# Load variables from .env file
load_dotenv()

"""
Vote Rakshak V2 Configuration
Update these values after deploying VoteRakshakV2.sol contract
"""

# JWT Configuration
JWT_SECRET = os.getenv("JWT_SECRET", "default_insecure_jwt")

# Blockchain Configuration (Ganache)
RPC_URL = os.getenv("RPC_URL", "http://127.0.0.1:7545")

# Google Gemini API Key for AI Chatbot
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# IMPORTANT: Update these after deploying the V2 contract
CONTRACT_ADDRESS = os.getenv("CONTRACT_ADDRESS", "")

# Admin account from Ganache
ADMIN_ACCOUNT = os.getenv("ADMIN_ACCOUNT", "")
ADMIN_PRIVATE_KEY = os.getenv("ADMIN_PRIVATE_KEY", "")

# ABI Path
ABI_PATH = os.getenv("ABI_PATH", "")

# MySQL Configuration (also in models.py)
MYSQL_CONFIG = {
    "user": os.getenv("MYSQL_USER", "root"),
    "password": os.getenv("MYSQL_PASSWORD", "admin123"),
    "host": os.getenv("MYSQL_HOST", "127.0.0.1"),
    "port": os.getenv("MYSQL_PORT", "3306"),
    "database": os.getenv("MYSQL_DB", "decentralised_voting")
}
