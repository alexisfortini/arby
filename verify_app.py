
import sys

try:
    import flask
    import pydantic
    import dotenv
    import schedule
    import markdown
    
    # Check for Gemini SDK
    try:
        import google.genai
    except ImportError:
        # Fallback check for older installs logic if needed, but we require google-genai
        raise ImportError("google.genai not found")

    print("✅ Dependencies verified.")
    sys.exit(0)
except ImportError as e:
    print(f"❌ Missing dependency: {e}")
    sys.exit(1)
except Exception as e:
    print(f"❌ Verification error: {e}")
    sys.exit(1)
