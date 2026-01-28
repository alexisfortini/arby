import os
import sys
import json
from dotenv import load_dotenv

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

from app.core.model_manager import ModelManager

def test_claude():
    load_dotenv()
    
    # Get the user's preferences to get the API key
    # Using the first user found or a specific ID if known
    user_id = "4e43e7b0-4ee9-4f39-8965-bc6cf072b8f3"
    pref_path = f"state/users/{user_id}/preferences.json"
    
    if not os.path.exists(pref_path):
        print(f"Error: Prefs not found at {pref_path}")
        return

    with open(pref_path, 'r') as f:
        prefs = json.load(f)
    
    api_keys = prefs.get('api_keys', {})
    claude_key = api_keys.get('anthropic')
    
    if not claude_key:
        print("Error: No Anthropic key found in preferences.")
        return
        
    print(f"Testing Claude with key: {claude_key[:10]}...")
    
    mm = ModelManager(base_dir=".", user_id=user_id, user_keys=api_keys)
    
    # Try a simple generate via ModelManager
    model_id = "claude-3-haiku-20240307" 
    
    try:
        print(f"Testing {model_id} via ModelManager...")
        # We need a system instruction and user prompt that triggering a tool use if we use mm.generate
        # But we can also test the provider directly
        provider = mm.providers.get('anthropic')
        if not provider:
            print("Error: Anthropic provider not initialized.")
            return
            
        res = provider.simple_generate(model_id, "You are a helpful assistant.", "Say hello!")
        print(f"Success (Simple): {res}")
        
    except Exception as e:
        print(f"Failed: {e}")

    # Now test with a LARGER prompt to see if we hit the 16384 limit
    print("\nTesting with large prompt (approx 10k chars)...")
    large_prompt = "Repeat after me 'I AM WORKING' but first, here is some filler text: " + ("Hello " * 2000)
    try:
        res = provider.simple_generate(model_id, "You are a helpful assistant.", large_prompt)
        print(f"Success (Large): {res[:50]}...")
    except Exception as e:
        print(f"Failed (Large): {e}")

if __name__ == "__main__":
    test_claude()
