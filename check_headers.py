import requests

url = "https://authserver.ely.by/minecraft/profile/skins"
try:
    response = requests.post(url, timeout=5)
    print(f"POST {url} -> {response.status_code}")
    print("Headers:", response.headers)
except Exception as e:
    print(e)
