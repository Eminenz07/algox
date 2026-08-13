import requests
import time

login_url = "https://algox-xto7.onrender.com/login"
logs_url = "https://algox-xto7.onrender.com/api/logs"

session = requests.Session()

# Poll until login succeeds and we can fetch logs
while True:
    try:
        resp = session.post(login_url, data={"email": "emmyadeoluwa@gmail.com", "password": "Emmy1282"}, timeout=10)
        if resp.status_code == 200:
            break
    except Exception:
        pass
    print("Waiting for server to boot...")
    time.sleep(5)

print("Server is online! Polling logs...")
seen_lines = set()
for _ in range(30): # check for 5 minutes
    try:
        resp = session.get(logs_url, timeout=10)
        if resp.status_code == 200:
            logs = resp.json().get("logs", "")
            lines = logs.strip().split("\n")
            for line in lines[-50:]:  # print only last 50 lines to avoid spam
                if "Failed to fetch balance" in line or "Exception" in line or "Traceback" in line or "Error" in line:
                    if line not in seen_lines:
                        print("LOG:", line)
                        seen_lines.add(line)
    except Exception as e:
        print("Polling error:", e)
    time.sleep(10)
