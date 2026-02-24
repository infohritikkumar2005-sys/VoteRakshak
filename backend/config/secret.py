# backend/config/secret.py
"""
Vote Rakshak V2 Configuration
Update these values after deploying VoteRakshakV2.sol contract
"""

# JWT Configuration
JWT_SECRET = "a534db40082c3f36472d5e2311c20f5ae610ab032e4067618d1d3400f4b440f1"

# Blockchain Configuration (Ganache)
RPC_URL = "http://127.0.0.1:7545"

# Google Gemini API Key for AI Chatbot (Get a free one at https://aistudio.google.com/app/apikey)
GEMINI_API_KEY = "AIzaSyADHhZm6R7TmRIUT4FkfXgweM3nMPsO75I"

# IMPORTANT: Update these after deploying the V2 contract
# Deploy VoteRakshakV2.sol and paste the new contract address here
CONTRACT_ADDRESS = "0x78a4Cab03F10616c41D3876712920819D0d74721"

# Admin account from Ganache (first account usually)
ADMIN_ACCOUNT = "0xA15522114508d025722a740E44815D89c1F83a6b"
ADMIN_PRIVATE_KEY = "0xb6bffabee7578f7ce9dc7ddccccff88c4af55425dbe5cab594052490f293d2eb"

# ABI Path - Update to V2 contract ABI
ABI_PATH = r"C:\Users\hriti\Desktop\vote rakshak\Vote-Rakshak---a-decentralised-voting-system-with-face-authentication-main\contracts\VoteRakshakV2.json"

# MySQL Configuration (also in models.py)
MYSQL_CONFIG = {
    "user": "root",
    "password": "admin123",
    "host": "127.0.0.1",
    "port": "3306",
    "database": "decentralised_voting"
}
