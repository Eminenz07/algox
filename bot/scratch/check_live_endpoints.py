import requests
import json

login_url = "https://algox-xto7.onrender.com/login"
creds_url = "https://algox-xto7.onrender.com/api/credentials"
state_url = "https://algox-xto7.onrender.com/api/state"
logs_url = "https://algox-xto7.onrender.com/api/logs"

session = requests.Session()

# 1. Log in
print("Logging in...")
login_payload = {
    "email": "emmyadeoluwa@gmail.com",
    "password": "Emmy1282"
}
resp = session.post(login_url, data=login_payload, timeout=15)
print("Login Status:", resp.status_code)
print("Login Final URL:", resp.url)

# 2. Get credentials
print("\nFetching /api/credentials...")
resp = session.get(creds_url, timeout=15)
print("Credentials Status:", resp.status_code)
try:
    print("Credentials JSON:", resp.json())
except Exception:
    print("Credentials Raw Text (failed to parse):", resp.text[:500])

# 3. Get state
print("\nFetching /api/state...")
resp = session.get(state_url, timeout=15)
print("State Status:", resp.status_code)
try:
    print("State JSON:", resp.json())
except Exception:
    print("State Raw Text (failed to parse):", resp.text[:500])

# 4. Get logs
print("\nFetching /api/logs...")
resp = session.get(logs_url, timeout=15)
print("Logs Status:", resp.status_code)
try:
    print("Logs JSON:", resp.json().get("logs", "No logs returned.")[:1000])
except Exception:
    print("Logs Raw Text (failed to parse):", resp.text[:500])
