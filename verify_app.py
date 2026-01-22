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
    
    print("Checking server module...")
    # Just import, don't run
    from app.web import server
    
    print("✅ Logic Check Passed: No Syntax Errors.")
    sys.exit(0)
except Exception as e:
    print(f"❌ Verification Failed: {e}")
    sys.exit(1)
