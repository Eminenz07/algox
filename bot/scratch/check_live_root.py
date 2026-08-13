import urllib.request
import urllib.error

url = "https://algox-xto7.onrender.com/"
try:
    print(f"Requesting {url}...")
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=15) as response:
        print("Success! Status:", response.status)
        print("Final URL:", response.url)
        print("Headers:", dict(response.headers))
        print("Body snippet:", response.read()[:500])
except urllib.error.HTTPError as e:
    print("HTTPError:", e.code)
    print("Headers:", dict(e.headers))
    print("Body snippet:", e.read()[:500])
except Exception as e:
    print("Failed:", e)
