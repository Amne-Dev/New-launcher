import json
import urllib.request
import urllib.error

class ElyByAuth:
    AUTH_URL = "https://authserver.ely.by/auth/authenticate"
    
    @staticmethod
    def authenticate(username, password):
        payload = {
            "agent": {
                "name": "Minecraft",
                "version": 1
            },
            "username": username,
            "password": password,
            "requestUser": True
        }
        
        try:
            data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(
                ElyByAuth.AUTH_URL, 
                data=data, 
                headers={'Content-Type': 'application/json'}
            )
            
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status == 200:
                    return json.loads(response.read().decode('utf-8'))
                return {"error": f"Authentication failed (Status {response.status})"}
                
        except urllib.error.HTTPError as e:
            return {"error": f"Authentication failed: {e.code} {e.reason}"}
        except Exception as e:
            return {"error": str(e)}
