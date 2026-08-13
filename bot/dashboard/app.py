import time
import logging
import os
import json
import mimetypes
import bcrypt

from flask import Flask, render_template, jsonify, request, redirect, url_for, flash
from flask_login import UserMixin, LoginManager, login_user, logout_user, login_required, current_user
from exchange import BybitClient
from security import encrypt_text, decrypt_text
import db_model

logger = logging.getLogger(__name__)

# Ensure proper MIME types for static assets
mimetypes.add_type('text/css', '.css')
mimetypes.add_type('application/javascript', '.js')

base_dir = os.path.dirname(os.path.abspath(__file__))
app = Flask(
    __name__,
    template_folder=os.path.join(base_dir, "templates"),
    static_folder=os.path.join(base_dir, "static")
)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "algox_secret_super_key")

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

_config = None

class FlaskUser(UserMixin):
    def __init__(self, user_dict):
        self.id = user_dict["id"]
        self.email = user_dict["email"]
        self.username = user_dict["username"]
        self.subscription_status = user_dict["subscription_status"]

@login_manager.user_loader
def load_user(user_id):
    u = db_model.get_user_by_id(int(user_id))
    if u:
        return FlaskUser(u)
    return None

def init_dashboard(config):
    global _config
    _config = config

def verify_demo_key(api_key: str, api_secret: str) -> bool:
    """Verifies that the API key is valid on Bybit Demo server."""
    try:
        client = BybitClient(api_key=api_key, api_secret=api_secret, demo=True)
        # Attempt to read balance - this will throw an exception if keys are real/invalid on demo
        client.session.get_wallet_balance(accountType="UNIFIED")
        return True
    except Exception as e:
        logger.warning("Bybit API key verification failed: %s", e)
        return False

# ── Auth Routes ───────────────────────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
        
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        
        user = db_model.get_user_by_email(email)
        if user and bcrypt.checkpw(password.encode('utf-8'), user["password_hash"].encode('utf-8')):
            login_user(FlaskUser(user))
            return redirect(url_for("index"))
        else:
            flash("Invalid email or password.", "error")
            
    return render_template("login.html")

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
        
    if request.method == "POST":
        email = request.form.get("email")
        username = request.form.get("username")
        password = request.form.get("password")
        
        # Check if already exists
        if db_model.get_user_by_email(email):
            flash("Email is already registered.", "error")
        else:
            try:
                db_model.create_user(email, username, password)
                flash("Account created! Please log in.", "success")
                return redirect(url_for("login"))
            except Exception as e:
                flash(f"Failed to create account: {e}", "error")
                
    return render_template("signup.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))

# ── Core Dashboard Routes ─────────────────────────────────────────────────────

@app.route("/")
@login_required
def index():
    return render_template("dashboard.html")

@app.route("/api/state")
@login_required
def api_state():
    # Fetch active and historical trades from Neon Postgres for the current user
    trades = db_model.get_user_trades(current_user.id, limit=50)
    
    # Separate open and closed
    open_list = [t for t in trades if t["outcome"] == "OPEN"]
    closed_list = [t for t in trades if t["outcome"] != "OPEN"]
    
    # Fetch balance from Bybit using their credentials
    balance = 0.0
    creds = db_model.get_user_credentials(current_user.id)
    if creds:
        try:
            master_key = os.environ.get("ALGOX_ENCRYPTION_KEY")
            api_secret = decrypt_text(creds["encrypted_api_secret"], creds["encryption_iv"], master_key)
            client = BybitClient(api_key=creds["api_key"], api_secret=api_secret, demo=True)
            balance = round(client.get_equity(), 2)
        except Exception as e:
            logger.error("Failed to fetch balance for user %s: %s", current_user.username, e, exc_info=True)
            
    return jsonify({
        "trades": open_list,
        "history": closed_list,
        "balance": balance,
        "has_credentials": creds is not None
    })

@app.route("/api/credentials", methods=["GET", "POST", "DELETE"])
@login_required
def api_credentials():
    if request.method == "GET":
        creds = db_model.get_user_credentials(current_user.id)
        if creds:
            return jsonify({
                "has_credentials": True,
                "api_key": creds["api_key"]
            })
        return jsonify({"has_credentials": False})
        
    elif request.method == "POST":
        data = request.json
        api_key = data.get("api_key")
        api_secret = data.get("api_secret")
        
        if not api_key or not api_secret:
            return jsonify({"success": False, "error": "API Key and Secret are required."}), 400
            
        # Verify Demo key
        if not verify_demo_key(api_key, api_secret):
            return jsonify({
                "success": False, 
                "error": "Authentication failed. Make sure this is a valid BYBIT DEMO API key (Production keys are not allowed for safety)."
            }), 400
            
        # Encrypt Secret
        master_key = os.environ.get("ALGOX_ENCRYPTION_KEY")
        enc_secret, iv = encrypt_text(api_secret, master_key)
        
        try:
            db_model.save_user_credentials(current_user.id, api_key, enc_secret, iv)
            return jsonify({"success": True, "message": "Demo API Keys connected successfully!"})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
            
    elif request.method == "DELETE":
        try:
            db_model.delete_user_credentials(current_user.id)
            return jsonify({"success": True, "message": "API Keys disconnected."})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/settings", methods=["GET", "POST"])
@login_required
def api_settings():
    global _config
    is_admin = (current_user.subscription_status == "admin")
    
    if request.method == "POST":
        try:
            data = request.json
            
            # Save user settings to database
            leverage = int(data.get("leverage", 10))
            risk_mode = data.get("risk_mode", "PERCENT")
            risk_amount = float(data.get("risk_amount", 1.0))
            db_model.update_user_settings(current_user.id, leverage, risk_mode, risk_amount)
            
            if is_admin and "config" in data:
                # Admins can edit full configuration parameters
                admin_cfg = data["config"]
                for cat, submap in admin_cfg.items():
                    if cat in _config:
                        for subkey, subval in submap.items():
                            if subkey in _config[cat]:
                                _config[cat][subkey] = subval
                                
                # Save configuration changes
                with open("config.json", "w") as f:
                    json.dump(_config, f, indent=2)
                
            return jsonify({"status": "success", "message": "Settings saved successfully!"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 400

    # GET request: return sanitized settings
    creds = db_model.get_user_credentials(current_user.id)
    user_settings = {
        "leverage": creds["leverage"] if creds else 10,
        "risk_mode": creds["risk_mode"] if creds else "PERCENT",
        "risk_amount": creds["risk_amount"] if creds else 1.0
    }

    sanitized = {}
    for k, v in _config.items():
        if k in ("exchange", "telegram") and not is_admin:
            continue
        sanitized[k] = v
        
    return jsonify({
        "config": sanitized,
        "user_settings": user_settings,
        "is_admin": is_admin
    })

@app.route("/api/logs")
@login_required
def api_logs():
    # Only admin users can read system logs
    if current_user.subscription_status != "admin":
        return jsonify({"logs": "Unauthorized."}), 403
        
    try:
        log_path = "logs/bot.log"
        if not os.path.exists(log_path):
            return jsonify({"logs": "Log file not found."})
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            last_lines = lines[-150:]
            return jsonify({"logs": "".join(last_lines)})
    except Exception as exc:
        return jsonify({"logs": f"Error reading logs: {exc}"}), 500

# ── Server Run Wrapper ────────────────────────────────────────────────────────

def run(host: str = "0.0.0.0", port: int = 5000):
    logger.info("SaaS Web Dashboard running at http://%s:%d", host, port)
    app.run(host=host, port=port, debug=False)
