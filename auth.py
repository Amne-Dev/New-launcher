import json
import urllib.request
import urllib.error
import time

class ElyByAuth:
    AUTH_URL = "https://authserver.ely.by/auth/authenticate"
    
    @staticmethod
    def authenticate(username, password, max_retries=3, timeout=10):
        """
        Authenticate with Ely.by service.
        
        Args:
            username: Ely.by username or email
            password: Account password
            max_retries: Maximum number of retry attempts (default: 3)
            timeout: Request timeout in seconds (default: 10)
            
        Returns:
            dict: Authentication response or error dict
        """
        if not username or not password:
            return {"error": "Username and password are required"}
        
        payload = {
            "agent": {
                "name": "Minecraft",
                "version": 1
            },
            "username": username,
            "password": password,
            "requestUser": True
        }
        
        last_error = None
        
        for attempt in range(max_retries):
            try:
                data = json.dumps(payload).encode('utf-8')
                req = urllib.request.Request(
                    ElyByAuth.AUTH_URL, 
                    data=data, 
                    headers={
                        'Content-Type': 'application/json',
                        'User-Agent': 'NewLauncher/1.8.2'
                    }
                )
                
                with urllib.request.urlopen(req, timeout=timeout) as response:
                    if response.status == 200:
                        result = json.loads(response.read().decode('utf-8'))
                        # Validate response has required fields
                        if 'accessToken' in result and 'selectedProfile' in result:
                            return result
                        else:
                            return {"error": "Invalid authentication response format"}
                    else:
                        return {"error": f"Authentication failed (Status {response.status})"}
                        
            except urllib.error.HTTPError as e:
                # Read error response body for better error messages
                try:
                    error_body = e.read().decode('utf-8')
                    error_data = json.loads(error_body)
                    error_msg = error_data.get('errorMessage', error_data.get('error', str(e.reason)))
                except:
                    error_msg = f"{e.code} {e.reason}"
                
                # Don't retry on authentication failure (401) or bad request (400)
                if e.code in [400, 401, 403]:
                    return {"error": f"Authentication failed: {error_msg}"}
                
                last_error = {"error": f"Server error ({e.code}): {error_msg}"}
                
            except urllib.error.URLError as e:
                last_error = {"error": f"Network error: {e.reason}"}
                
            except json.JSONDecodeError as e:
                return {"error": "Invalid server response (not JSON)"}
                
            except Exception as e:
                last_error = {"error": f"Unexpected error: {str(e)}"}
            
            # Wait before retry (exponential backoff)
            if attempt < max_retries - 1:
                wait_time = (2 ** attempt) * 0.5  # 0.5s, 1s, 2s
                time.sleep(wait_time)
        
        # All retries failed
        if last_error:
            last_error["error"] = f"{last_error['error']} (after {max_retries} attempts)"
        return last_error or {"error": "Authentication failed after multiple attempts"}
