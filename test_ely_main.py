import requests

url = "https://ely.by/minecraft/profile/skins"
try:
    response = requests.post(url, timeout=5)
    print(f"POST {url} -> {response.status_code}")
except Exception as e:
    print(f"POST {url} -> Error: {e}")
