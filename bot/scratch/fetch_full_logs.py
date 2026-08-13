import requests

login_url = "https://algox-xto7.onrender.com/login"
logs_url = "https://algox-xto7.onrender.com/api/logs"

session = requests.Session()
session.post(login_url, data={"email": "emmyadeoluwa@gmail.com", "password": "Emmy1282"}, timeout=15)

resp = session.get(logs_url, timeout=15)
logs = resp.json().get("logs", "No logs.")
print("=== SERVER LOGS ===")
print(logs[-4000:])  # print last 4000 chars of logs
