import os
import psycopg2
import json
from datetime import datetime, timezone

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

if not conn_str:
    print("DATABASE_URL is missing.")
    exit(1)

# 1. Read history.json
history_path = "history.json"
if not os.path.exists(history_path):
    history_path = "bot/history.json"

if os.path.exists(history_path):
    with open(history_path, "r") as f:
        hist_trades = json.load(f)
else:
    hist_trades = []
    print("history.json not found.")

conn = psycopg2.connect(conn_str)
try:
    with conn.cursor() as cur:
        # Get user ID of His_Emi
        cur.execute("SELECT id FROM users WHERE username = 'His_Emi'")
        row = cur.fetchone()
        if not row:
            print("User His_Emi not found.")
            exit(1)
        user_id = row[0]
        
        # 2. Insert historical trades from history.json if not already present
        for t in hist_trades:
            # Check if this trade is already logged in Postgres to prevent duplicates
            cur.execute("""
                SELECT id FROM trades 
                WHERE user_id = %s AND symbol = %s AND direction = %s AND entry_price = %s
            """, (user_id, t["symbol"], t["direction"], t["entry"]))
            
            existing = cur.fetchone()
            if not existing:
                cur.execute("""
                    INSERT INTO trades (user_id, symbol, direction, entry_price, close_price, qty, pnl, outcome, closed_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (user_id, t["symbol"], t["direction"], t["entry"], t["close"], t["qty"], t["pnl"], t["outcome"], datetime.now(timezone.utc)))
                print(f"Imported historical trade: {t['symbol']} {t['direction']} at {t['entry']}")
            else:
                print(f"Trade already exists: {t['symbol']} {t['direction']} at {t['entry']}")

        # 3. Fix Trade ID 7 (BTCUSDT trade that got the wrong exit price/PnL due to API sync lag)
        # Entry price: 63692.4, actual exit price: 63373.7, actual PnL: -604.14514518
        cur.execute("""
            UPDATE trades 
            SET close_price = 63373.7, pnl = -604.14514518, outcome = 'SL'
            WHERE user_id = %s AND symbol = 'BTCUSDT' AND entry_price = 63692.4
        """, (user_id,))
        print("Updated Trade ID 7 with correct Bybit execution values (exit: 63373.7, PnL: -604.15).")
        
        conn.commit()
finally:
    conn.close()
