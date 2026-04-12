"""
Create OAuth2 Client ID for the Firebase project and enable Google Sign-In.
"""
import json
import urllib.request
from google.oauth2 import service_account
from google.auth.transport.requests import Request

CRED_FILE = "./fir-admin-5be88-firebase-adminsdk-fbsvc-cdd751856c.json"
PROJECT_ID = "fir-admin-5be88"
PROJECT_NUMBER = "368885900712"

cred = service_account.Credentials.from_service_account_file(
    CRED_FILE,
    scopes=["https://www.googleapis.com/auth/cloud-platform"]
)
request = Request()
cred.refresh(request)
token = cred.token

# Step 1: Create an OAuth2 brand (consent screen)
print("=== Step 1: Creating OAuth Consent Screen / Brand ===")
brand_url = f"https://iap.googleapis.com/v1/projects/{PROJECT_NUMBER}/brands"

# First let's try listing existing brands via the oauth2 API
brand_list_url = f"https://oauth2.googleapis.com/v1/projects/{PROJECT_NUMBER}/brands"

# Use Cloud Resource Manager to check project details
print("\n=== Checking project access ===")
project_url = f"https://cloudresourcemanager.googleapis.com/v1/projects/{PROJECT_ID}"
req = urllib.request.Request(project_url, headers={"Authorization": f"Bearer {token}"})
try:
    response = urllib.request.urlopen(req)
    data = json.loads(response.read())
    print(f"Project: {data.get('name')}")
    print(f"Number: {data.get('projectNumber')}")
except urllib.error.HTTPError as e:
    print(f"Error {e.code}: {e.read().decode()}")

# Step 2: Try creating OAuth client via the Cloud Client Auth Config API
print("\n=== Step 2: Creating OAuth2 Web Client ===")
clients_url = f"https://clientauthconfig.googleapis.com/v1/projects/{PROJECT_NUMBER}/clients"
client_payload = json.dumps({
    "displayName": "FestiFlip Web Client",
    "clientType": "WEB",
    "allowedRedirectUris": [
        "https://web-production-8c7e93.up.railway.app/auth/callback",
        "http://localhost:8000/auth/callback" 
    ],
    "allowedScopes": ["openid", "email", "profile"]
}).encode("utf-8")

req = urllib.request.Request(clients_url, data=client_payload, headers={
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
})
try:
    response = urllib.request.urlopen(req)
    data = json.loads(response.read())
    print("Created OAuth2 client!")
    print(json.dumps(data, indent=2))
except urllib.error.HTTPError as e:
    error_body = e.read().decode()
    print(f"Error {e.code}: {error_body}")
    
    # If already exists, try listing
    if e.code in (403, 409):
        print("\nTrying to list existing clients...")
        req = urllib.request.Request(clients_url, headers={"Authorization": f"Bearer {token}"})
        try:
            response = urllib.request.urlopen(req)
            data = json.loads(response.read())
            print(json.dumps(data, indent=2))
        except urllib.error.HTTPError as e2:
            print(f"List error {e2.code}: {e2.read().decode()}")
