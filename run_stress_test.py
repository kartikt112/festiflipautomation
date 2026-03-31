import os
import sys
from app.config import settings

# Add the artifact directory to the Python path so it can import ai_router_poc
sys.path.append('/Users/prakashtupe/.gemini/antigravity/brain/db2f2a68-789e-469c-a0b6-c2abc3f66728/')

with open('/Users/prakashtupe/.gemini/antigravity/brain/db2f2a68-789e-469c-a0b6-c2abc3f66728/stress_test_router.py', 'r') as f:
    code = f.read()
exec(code)
