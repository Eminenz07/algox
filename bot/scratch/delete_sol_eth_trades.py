import os
import psycopg2

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

conn = psycopg2.connect(conn_str)
try:
    with conn.cursor() as cur:
        # Delete SOLUSDT and ETHUSDT trades
        cur.execute("DELETE FROM trades WHERE symbol IN ('SOLUSDT', 'ETHUSDT')")
        deleted_count = cur.rowcount
        conn.commit()
        print(f"Successfully deleted {deleted_count} SOL and ETH trades from trades history.")
finally:
    conn.close()
