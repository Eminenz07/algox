import os
import sys
# Add parent directory to path so we can import from bot folder
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
from psycopg2.extras import RealDictCursor
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import requests
import json
import time

# Sync time offset
original_time = time.time
try:
    resp = requests.get("https://api.bybit.com/v3/public/time", timeout=10).json()
    server_time = float(resp["result"]["timeSecond"])
    local_time = original_time()
    offset = server_time - local_time
    # Monkeypatch time.time
    time.time = lambda: original_time() + offset
except Exception as e:
    pass

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

conn = psycopg2.connect(conn_str)
try:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM users WHERE username = 'His_Emi'")
        user = cur.fetchone()
        if user:
            cur.execute("SELECT * FROM user_credentials WHERE user_id = %s", (user["id"],))
            creds = cur.fetchone()
            if creds:
                api_secret = AESGCM(bytes.fromhex(master_key_hex)).decrypt(bytes.fromhex(creds["encryption_iv"]), bytes.fromhex(creds["encrypted_api_secret"]), None).decode('utf-8')
                api_key = creds["api_key"]
                
                from pybit.unified_trading import HTTP
                session = HTTP(testnet=False, demo=True, api_key=api_key, api_secret=api_secret)
                
                # Fetch trade history
                res = session.get_closed_pnl(category="linear", limit=10)
                print("Closed profits:")
                print(json.dumps(res.get("result", {}).get("list", []), indent=2))
finally:
    conn.close()
