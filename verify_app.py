import sys
import os

print("Verifying Arby App integrity...")

try:
    # Add project root to path
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__))))
    
    print("Checking core modules...")
    import app.core.agent
    import app.core.model_manager
    import app.core.cookbook_manager
    import app.core.inventory_manager
    import app.core.calendar_manager
    import app.core.user_manager
    
    print("Checking provider libraries...")
    import google.genai
    import openai
    import anthropic
    
    print("Checking server module syntax...")
    # This imports the Flask app object and defines routes
    from app.web.server import app as flask_app
    
    print("✅ Logic Check Passed: No Syntax Errors.")
    sys.exit(0)
except Exception as e:
    import traceback
    traceback.print_exc()
    print(f"❌ Verification Failed: {e}")
    sys.exit(1)
