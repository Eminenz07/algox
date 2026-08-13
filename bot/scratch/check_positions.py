import os
import sys
import psycopg2
from psycopg2.extras import RealDictCursor
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import requests
import json

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

if not conn_str or not master_key_hex:
    print("Missing env variables.")
    exit(1)

def decrypt_text(enc_hex: str, iv_hex: str, key_hex: str) -> str:
    key = bytes.fromhex(key_hex)
    iv = bytes.fromhex(iv_hex)
    data = bytes.fromhex(enc_hex)
    aesgcm = AESGCM(key)
    decrypted = aesgcm.decrypt(iv, data, None)
    return decrypted.decode('utf-8')

# Query admin user (username = 'His_Emi')
conn = psycopg2.connect(conn_str)
try:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM users WHERE username = 'His_Emi'")
        user = cur.fetchone()
        print("User:", user)
        if user:
            cur.execute("SELECT * FROM user_credentials WHERE user_id = %s", (user["id"],))
            creds = cur.fetchone()
            print("Credentials found:", creds is not None)
            if creds:
                # Decrypt api_secret
                api_secret = decrypt_text(creds["encrypted_api_secret"], creds["encryption_iv"], master_key_hex)
                api_key = creds["api_key"]
                
                # Query Bybit directly using pybit with large recv_window to prevent local clock desync errors
                from pybit.unified_trading import HTTP
                session = HTTP(
                    testnet=False,
                    demo=True,
                    api_key=api_key,
                    api_secret=api_secret,
                    recv_window=60000
                )
                
                res = session.get_positions(category="linear", settleCoin="USDT")
                print("Positions response:")
                active_found = False
                for p in res.get("result", {}).get("list", []):
                    if float(p.get("size", 0)) != 0:
                        active_found = True
                        print(json.dumps(p, indent=2))
                if not active_found:
                    print("No active open positions on Bybit Demo account.")
finally:
    conn.close()
