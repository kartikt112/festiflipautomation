import json
import urllib.request
from google.oauth2 import service_account
from google.auth.transport.requests import Request

CRED_FILE = "./fir-admin-5be88-firebase-adminsdk-fbsvc-cdd751856c.json"
PROJECT_ID = "fir-admin-5be88"
DOMAIN = "web-production-8c7e93.up.railway.app"

try:
    print("Loading credentials...")
    cred = service_account.Credentials.from_service_account_file(
        CRED_FILE, 
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    request = Request()
    cred.refresh(request)
    token = cred.token

    url = f"https://identitytoolkit.googleapis.com/admin/v2/projects/{PROJECT_ID}/config"
    
    print("Fetching current config...")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    response = urllib.request.urlopen(req)
    data = json.loads(response.read())
    
    current_domains = data.get("authorizedDomains", [])
    print(f"Current domains: {current_domains}")
    
    if DOMAIN not in current_domains:
        current_domains.append(DOMAIN)
        
        print("Updating config...")
        # Field mask is required for PATCH
        update_url = f"{url}?updateMask=authorizedDomains"
        payload = json.dumps({"authorizedDomains": current_domains}).encode("utf-8")
        
        req = urllib.request.Request(update_url, data=payload, headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }, method="PATCH")
        
        response = urllib.request.urlopen(req)
        print("Successfully updated authorized domains!")
        print(json.loads(response.read()).get("authorizedDomains"))
    else:
        print("Domain is already authorized.")

except Exception as e:
    print(f"Error: {e}")
