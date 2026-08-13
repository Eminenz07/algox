import os
import psycopg2
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

def load_env():
    paths = [".env", "../.env"]
    for path in paths:
        if os.path.exists(path):
            with open(path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, val = line.split("=", 1)
                        os.environ[key] = val.strip().strip('"').strip("'")
            break

load_env()
conn_str = os.environ.get("DATABASE_URL")
master_key_hex = os.environ.get("ALGOX_ENCRYPTION_KEY")
bybit_key = os.environ.get("BYBIT_API_KEY")
bybit_secret = os.environ.get("BYBIT_API_SECRET")

if not conn_str or not master_key_hex or not bybit_key or not bybit_secret:
    print("Missing variables.")
    exit(1)

def encrypt_text(text: str, key_hex: str):
    key = bytes.fromhex(key_hex)
    aesgcm = AESGCM(key)
    iv = os.urandom(12)
    encrypted = aesgcm.encrypt(iv, text.encode('utf-8'), None)
    return encrypted.hex(), iv.hex()

# Encrypt secret
enc_secret, iv = encrypt_text(bybit_secret, master_key_hex)

conn = psycopg2.connect(conn_str)
try:
    with conn.cursor() as cur:
        # Get user ID of His_Emi
        cur.execute("SELECT id FROM users WHERE username = 'His_Emi'")
        row = cur.fetchone()
        if row:
            user_id = row[0]
            # Save credentials
            cur.execute("""
                INSERT INTO user_credentials (user_id, api_key, encrypted_api_secret, encryption_iv)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE 
                SET api_key = EXCLUDED.api_key, 
                    encrypted_api_secret = EXCLUDED.encrypted_api_secret, 
                    encryption_iv = EXCLUDED.encryption_iv,
                    updated_at = CURRENT_TIMESTAMP
            """, (user_id, bybit_key, enc_secret, iv))
            conn.commit()
            print("Credentials successfully encrypted and saved to database for user ID:", user_id)
        else:
            print("User His_Emi not found.")
finally:
    conn.close()
