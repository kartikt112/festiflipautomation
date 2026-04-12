import firebase_admin
from firebase_admin import credentials, auth

cred = credentials.Certificate("./fir-admin-5be88-firebase-adminsdk-fbsvc-cdd751856c.json")
firebase_admin.initialize_app(cred)

try:
    print("Methods available on firebase_admin.auth:")
    methods = [m for m in dir(auth) if not m.startswith('_')]
    print(", ".join(methods))
    
    config = auth.get_project_config()
    print("Authorized domains:")
    print(getattr(config, 'authorized_domains', 'Not found'))
    
    # Try to add domain if update is available
    if hasattr(auth, 'update_project_config'):
        print("update_project_config is available. Trying to update domains...")
        current_domains = config.authorized_domains or []
        if 'web-production-8c7e93.up.railway.app' not in current_domains:
            new_domains = list(current_domains) + ['web-production-8c7e93.up.railway.app']
            auth.update_project_config(authorized_domains=new_domains)
            print("Successfully added domain via Python SDK!")
        else:
            print("Domain is already authorized.")
except Exception as e:
    print(f"Error: {e}")
