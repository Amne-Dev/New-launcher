import requests

endpoints = [
    {
        "url": "https://authserver.ely.by/minecraft/profile/skins",
        "method": "POST"
    },
    {
        "url": "https://skinsystem.ely.by/api/skins",
        "method": "POST"
    },
    {
        "url": "https://ely.by/api/skin/upload",
        "method": "POST"
    }
]

for ep in endpoints:
    try:
        if ep["method"] == "POST":
            response = requests.post(ep["url"], timeout=5)
        else:
            response = requests.get(ep["url"], timeout=5)
        print(f"{ep['method']} {ep['url']} -> {response.status_code}")
    except Exception as e:
        print(f"{ep['method']} {ep['url']} -> Error: {e}")
