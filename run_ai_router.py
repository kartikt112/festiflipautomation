import asyncio
from app.config import settings

# Temporary wrapper to run the POC script since it needs the API key
import os
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

with open('/Users/prakashtupe/.gemini/antigravity/brain/db2f2a68-789e-469c-a0b6-c2abc3f66728/ai_router_poc.py', 'r') as f:
    code = f.read()
exec(code)
