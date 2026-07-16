"""
dashboard/app.py
Real-time web dashboard using Flask + Flask-SocketIO.
Pushes live trade state to all connected browser clients every second.
"""

import time
import logging
import threading
import os
import json

from flask            import Flask, render_template, jsonify, request
from flask_socketio   import SocketIO

logger = logging.getLogger(__name__)

app      = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# Shared state injected by main.py
_trade_manager = None
_exchange      = None
_config        = None
_start_time    = time.time()


def init_dashboard(trade_manager, exchange, config):
    """Called from main.py to inject dependencies."""
    global _trade_manager, _exchange, _config
    _trade_manager = trade_manager
    _exchange      = exchange
    _config        = config


# ── Background push loop ──────────────────────────────────────────────────────

def _push_loop():
    """Push state to all connected clients every second."""
    while True:
        try:
            if _trade_manager and _exchange:
                payload = {
                    "trades":   _trade_manager.get_all_trades(),
                    "history":  _trade_manager.get_history(),
                    "balance":  round(_exchange.get_equity(), 2),
                    "uptime":   int(time.time() - _start_time),
                    "ts":       int(time.time()),
                }
                socketio.emit("update", payload)
        except Exception as exc:
            logger.warning("Dashboard push error: %s", exc)
        time.sleep(1)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/state")
def api_state():
    if not _trade_manager:
        return jsonify({"error": "not ready"}), 503
    return jsonify({
        "trades":  _trade_manager.get_all_trades(),
        "history": _trade_manager.get_history(),
        "balance": round(_exchange.get_equity(), 2),
    })


@app.route("/api/logs")
def api_logs():
    try:
        log_path = "logs/bot.log"
        if not os.path.exists(log_path):
            return jsonify({"logs": "Log file not found."})
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            last_lines = lines[-150:]  # last 150 lines
            return jsonify({"logs": "".join(last_lines)})
    except Exception as exc:
        return jsonify({"logs": f"Error reading logs: {exc}"}), 500


@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    if not _config:
        return jsonify({"error": "not ready"}), 503
        
    if request.method == "POST":
        try:
            data = request.json
            allowed_categories = ["trading", "strategy", "dashboard"]
            for cat in allowed_categories:
                if cat in data:
                    for subkey, subval in data[cat].items():
                        current_val = _config[cat].get(subkey)
                        if current_val is not None:
                            # Cast value to match existing type
                            if isinstance(current_val, int):
                                _config[cat][subkey] = int(subval)
                            elif isinstance(current_val, float):
                                _config[cat][subkey] = float(subval)
                            elif isinstance(current_val, bool):
                                if str(subval).lower() in ("true", "1", "yes"):
                                    _config[cat][subkey] = True
                                else:
                                    _config[cat][subkey] = False
                            elif isinstance(current_val, list):
                                if isinstance(subval, str):
                                    _config[cat][subkey] = [x.strip() for x in subval.split(",") if x.strip()]
                                else:
                                    _config[cat][subkey] = list(subval)
                            else:
                                _config[cat][subkey] = str(subval)
                                
            # Save to config.json
            with open("config.json", "w") as f:
                json.dump(_config, f, indent=2)
                
            logger.info("Configuration updated via Dashboard: %s", data)
            return jsonify({"status": "success", "message": "Settings saved successfully!"})
        except Exception as exc:
            logger.error("Failed to save settings: %s", exc)
            return jsonify({"status": "error", "message": str(exc)}), 400

    # GET request
    # Return a sanitized config (hide Bybit API keys and Telegram tokens)
    sanitized = {}
    for k, v in _config.items():
        if k in ("exchange", "telegram"):
            sanitized[k] = {
                subkey: ("******" if subkey in ("api_key", "api_secret", "bot_token") else subval)
                for subkey, subval in v.items()
            }
        else:
            sanitized[k] = v
    return jsonify(sanitized)


# ── Startup ───────────────────────────────────────────────────────────────────

def run(host: str = "127.0.0.1", port: int = 5000):
    # Start background push thread
    t = threading.Thread(target=_push_loop, daemon=True)
    t.start()
    logger.info("Dashboard running at http://%s:%d", host, port)
    socketio.run(app, host=host, port=port, debug=False, allow_unsafe_werkzeug=True, use_reloader=False)
