import requests

url = "https://authserver.ely.by/minecraft/profile/skins"
try:
    response = requests.delete(url, timeout=5)
    print(f"DELETE {url} -> {response.status_code}")
except Exception as e:
    print(f"DELETE {url} -> Error: {e}")
