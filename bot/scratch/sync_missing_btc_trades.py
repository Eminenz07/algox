import os
import psycopg2
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

        # 1. Insert Position 9 (Win)
        # Entry: 63575.2, exit: 63942.7, qty: 1.258, pnl: 374.08, direction: LONG
        cur.execute("""
            SELECT id FROM trades 
            WHERE user_id = %s AND symbol = 'BTCUSDT' AND entry_price = 63575.2
        """, (user_id,))
        if not cur.fetchone():
            cur.execute("""
                INSERT INTO trades (user_id, symbol, direction, entry_price, close_price, qty, pnl, outcome, closed_at)
                VALUES (%s, 'BTCUSDT', 'LONG', 63575.2, 63942.7, 1.258, 374.08, '1R WIN', %s)
            """, (user_id, datetime.fromtimestamp(1786598146414/1000, tz=timezone.utc)))
            print("Inserted missing Win (Position 9) entry 63575.2")
        else:
            print("Win (Position 9) already exists.")

        # 2. Insert Position 8 (Loss)
        # Entry: 63589.7, exit: 63907.5, qty: 1.258, pnl: -488.00, direction: SHORT
        cur.execute("""
            SELECT id FROM trades 
            WHERE user_id = %s AND symbol = 'BTCUSDT' AND entry_price = 63589.7
        """, (user_id,))
        if not cur.fetchone():
            cur.execute("""
                INSERT INTO trades (user_id, symbol, direction, entry_price, close_price, qty, pnl, outcome, closed_at)
                VALUES (%s, 'BTCUSDT', 'SHORT', 63589.7, 63907.5, 1.258, -488.00, 'SL', %s)
            """, (user_id, datetime.fromtimestamp(1786612508381/1000, tz=timezone.utc)))
            print("Inserted missing Loss (Position 8) entry 63589.7")
        else:
            print("Loss (Position 8) already exists.")

        conn.commit()

        # 3. Print current trade stats in database to verify
        from psycopg2.extras import RealDictCursor
        with conn.cursor(cursor_factory=RealDictCursor) as dict_cur:
            dict_cur.execute("SELECT symbol, direction, entry_price, close_price, outcome, pnl FROM trades WHERE user_id = %s", (user_id,))
            trades = dict_cur.fetchall()
            
            wins = [t for t in trades if t["outcome"] == "1R WIN"]
            losses = [t for t in trades if t["outcome"] != "1R WIN"]
            
            print("\nFinal Verification:")
            print(f"Total BTC Trades: {len(trades)}")
            print(f"Wins: {len(wins)} | Losses: {len(losses)}")
            for idx, t in enumerate(trades, 1):
                print(f"  {idx}. {t['symbol']} {t['direction']} | Entry: {t['entry_price']} | Exit: {t['close_price']} | Outcome: {t['outcome']} | PnL: {t['pnl']:.2f}")

finally:
    conn.close()
