import os
import psycopg2
from psycopg2.extras import RealDictCursor

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
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM trades LIMIT 20")
        rows = cur.fetchall()
        print("Trades in database:")
        for r in rows:
            print(dict(r))
finally:
    conn.close()
