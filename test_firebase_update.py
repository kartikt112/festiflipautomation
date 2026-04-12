import firebase_admin
from firebase_admin import credentials, auth

cred = credentials.Certificate("./fir-admin-5be88-firebase-adminsdk-fbsvc-cdd751856c.json")
firebase_admin.initialize_app(cred)

try:
    # See what methods are available on auth
    print("Methods available on firebase_admin.auth:")
    methods = [m for m in dir(auth) if not m.startswith('_')]
    print(", ".join(methods))
    
    # Try getting project config
    config = auth.get_project_config()
    print("Authorized domains:", getattr(config, 'authorized_domains', 'Not found'))
except Exception as e:
    print(f"Error: {e}")
