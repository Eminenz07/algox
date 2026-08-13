import psycopg2
from psycopg2.extras import RealDictCursor
import bcrypt
import logging

logger = logging.getLogger(__name__)

# Connection string (set globally after loading config)
_db_url = None

def set_db_url(url: str):
    global _db_url
    _db_url = url

def get_connection():
    if not _db_url:
        raise ValueError("Database URL is not configured. Call set_db_url first.")
    return psycopg2.connect(_db_url)

def init_db(conn_str: str, admin_email: str, admin_password: str, admin_username: str):
    """Creates all database tables and seeds the admin user."""
    set_db_url(conn_str)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # 1. Create USERS table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    email VARCHAR(255) UNIQUE NOT NULL,
                    username VARCHAR(100) UNIQUE NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,
                    subscription_status VARCHAR(50) DEFAULT 'free',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            
            # 2. Create USER_CREDENTIALS table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_credentials (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER UNIQUE NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    api_key VARCHAR(255) NOT NULL,
                    encrypted_api_secret VARCHAR(255) NOT NULL,
                    encryption_iv VARCHAR(255) NOT NULL,
                    is_active BOOLEAN DEFAULT TRUE,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            # Migrations for settings configurations
            cur.execute("ALTER TABLE user_credentials ADD COLUMN IF NOT EXISTS leverage INTEGER DEFAULT 10;")
            cur.execute("ALTER TABLE user_credentials ADD COLUMN IF NOT EXISTS risk_mode VARCHAR(10) DEFAULT 'PERCENT';")
            cur.execute("ALTER TABLE user_credentials ADD COLUMN IF NOT EXISTS risk_amount DOUBLE PRECISION DEFAULT 1.0;")
            cur.execute("ALTER TABLE user_credentials ADD COLUMN IF NOT EXISTS fixed_capital DOUBLE PRECISION DEFAULT 50000.0;")

            # 3. Create TRADES table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    symbol VARCHAR(50) NOT NULL,
                    direction VARCHAR(10) NOT NULL,
                    entry_price DOUBLE PRECISION NOT NULL,
                    close_price DOUBLE PRECISION NOT NULL,
                    qty DOUBLE PRECISION NOT NULL,
                    pnl DOUBLE PRECISION NOT NULL,
                    outcome VARCHAR(50) NOT NULL,
                    closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Seed Admin User if not exists
            cur.execute("SELECT id FROM users WHERE email = %s", (admin_email,))
            if not cur.fetchone():
                pw_hash = bcrypt.hashpw(admin_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                cur.execute("""
                    INSERT INTO users (email, username, password_hash, subscription_status)
                    VALUES (%s, %s, %s, 'admin')
                """, (admin_email, admin_username, pw_hash))
                logger.info("Admin user successfully seeded.")
            
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error("Failed to initialize database: %s", e)
        raise e
    finally:
        conn.close()

# ── User CRUD Helpers ─────────────────────────────────────────────────────────

def get_user_by_id(user_id: int):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            return cur.fetchone()
    finally:
        conn.close()

def get_user_by_email(email: str):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE email = %s", (email,))
            return cur.fetchone()
    finally:
        conn.close()

def create_user(email: str, username: str, password_raw: str):
    conn = get_connection()
    try:
        pw_hash = bcrypt.hashpw(password_raw.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                INSERT INTO users (email, username, password_hash)
                VALUES (%s, %s, %s) RETURNING *
            """, (email, username, pw_hash))
            user = cur.fetchone()
        conn.commit()
        return user
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

# ── Credentials CRUD Helpers ──────────────────────────────────────────────────

def get_user_credentials(user_id: int):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM user_credentials WHERE user_id = %s", (user_id,))
            return cur.fetchone()
    finally:
        conn.close()

def save_user_credentials(user_id: int, api_key: str, encrypted_secret: str, iv: str):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO user_credentials (user_id, api_key, encrypted_api_secret, encryption_iv)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE 
                SET api_key = EXCLUDED.api_key, 
                    encrypted_api_secret = EXCLUDED.encrypted_api_secret, 
                    encryption_iv = EXCLUDED.encryption_iv,
                    updated_at = CURRENT_TIMESTAMP
            """, (user_id, api_key, encrypted_secret, iv))
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def delete_user_credentials(user_id: int):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM user_credentials WHERE user_id = %s", (user_id,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

# ── Trades CRUD Helpers ────────────────────────────────────────────────────────

def get_user_trades(user_id: int, limit: int = 100):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT * FROM trades 
                WHERE user_id = %s 
                ORDER BY closed_at DESC 
                LIMIT %s
            """, (user_id, limit))
            return cur.fetchall()
    finally:
        conn.close()

def log_trade(user_id: int, symbol: str, direction: str, entry_price: float, close_price: float, qty: float, pnl: float, outcome: str):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO trades (user_id, symbol, direction, entry_price, close_price, qty, pnl, outcome)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (user_id, symbol, direction, entry_price, close_price, qty, pnl, outcome))
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def update_user_settings(user_id: int, leverage: int, risk_mode: str, risk_amount: float, fixed_capital: float):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE user_credentials 
                SET leverage = %s, risk_mode = %s, risk_amount = %s, fixed_capital = %s, updated_at = CURRENT_TIMESTAMP
                WHERE user_id = %s
            """, (leverage, risk_mode, risk_amount, fixed_capital, user_id))
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()
