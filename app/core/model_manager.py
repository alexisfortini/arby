import os
import json
import time
import google.genai as genai
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None
try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None
from app.core.schemas import WeeklyPlan

# --- PROVIER WRAPPERS ---

class GeminiProvider:
    def __init__(self, api_key):
        self.client = genai.Client(api_key=api_key)

    def ping(self, model_id):
        try:
            print(f"DEBUG: Pinging Gemini model {model_id}...")
            self.client.models.generate_content(
                model=model_id,
                contents="Hello",
                config=genai.types.GenerateContentConfig(max_output_tokens=5)
            )
            return True
        except Exception as e:
            print(f"DEBUG: Gemini Ping Failed: {e}")
            raise e

    def generate(self, model_id, system_instruction, user_prompt, files=None, schema=WeeklyPlan):
        content_parts = []
        if files:
            for f in files:
                content_parts.append(genai.types.Part.from_uri(f.uri, mime_type=f.mime_type))
        content_parts.append(user_prompt)

        response = self.client.models.generate_content(
            model=model_id,
            contents=content_parts,
            config=genai.types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                response_schema=schema,
                max_output_tokens=8192
            )
        )
        if response.parsed:
            return response.parsed.model_dump()
        else:
            raise Exception("Gemini returned empty response")

    def simple_generate(self, model_id, system_instruction, user_prompt):
        response = self.client.models.generate_content(
            model=model_id,
            contents=user_prompt,
            config=genai.types.GenerateContentConfig(
                system_instruction=system_instruction
            )
        )
        return response.text

class OpenAIProvider:
    def __init__(self, api_key, base_url=None):
        if not OpenAI:
            raise ImportError("The 'openai' Python library is not installed.")
        self.client = OpenAI(api_key=api_key, base_url=base_url)

    def ping(self, model_id):
        try:
            print(f"DEBUG: Pinging OpenAI model {model_id}...")
            # Newer models (o1, o3, o4, gpt-5) use max_completion_tokens
            params = {
                "model": model_id,
                "messages": [{"role": "user", "content": "Reply OK"}]
            }
            if model_id.startswith(("o1", "o3", "o4", "gpt-5")):
                params["max_completion_tokens"] = 5
            else:
                params["max_tokens"] = 5
                
            self.client.chat.completions.create(**params)
            return True
        except Exception as e:
            print(f"DEBUG: OpenAI Ping Failed: {e}")
            raise e

    def generate(self, model_id, system_instruction, user_prompt, files=None, schema=WeeklyPlan):
        # OpenAI doesn't support file URIs the same way Gemini does (context caching).
        # handling file inputs for LLMs without native file-handle support is complex.
        
        try:
            completion = self.client.beta.chat.completions.parse(
                model=model_id,
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": user_prompt},
                ],
                response_format=schema,
            )
            return completion.choices[0].message.parsed.model_dump()
        except Exception as e:
            raise Exception(f"OpenAI/xAI Generation Error: {e}")

    def simple_generate(self, model_id, system_instruction, user_prompt):
        completion = self.client.chat.completions.create(
            model=model_id,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_prompt}
            ]
        )
        return completion.choices[0].message.content

class AnthropicProvider:
    def __init__(self, api_key):
        if not Anthropic:
            raise ImportError("The 'anthropic' Python library is not installed.")
        self.client = Anthropic(api_key=api_key)

    def ping(self, model_id):
        try:
            print(f"DEBUG: Pinging Anthropic model {model_id}...")
            if not self.client:
                print("DEBUG: Anthropic client is NONE!")
                raise Exception("Anthropic client is not initialized.")
            
            resp = self.client.messages.create(
                model=model_id,
                max_tokens=10,
                messages=[{"role": "user", "content": "Reply OK"}]
            )
            print(f"DEBUG: Anthropic Ping SUCCESS: {resp.id}")
            return True
        except Exception as e:
            print(f"DEBUG: Anthropic Ping Failed: {e}")
            raise e

    def generate(self, model_id, system_instruction, user_prompt, files=None, schema=WeeklyPlan):
        # Anthropic Tool Use for structured output
        schema_json = schema.model_json_schema()
        
        tool_name = "submit_data"
        tools = [{
            "name": tool_name,
            "description": "Submit structured data matching the requested schema.",
            "input_schema": schema_json
        }]

        try:
            print(f"DEBUG: Calling Anthropic model {model_id}...")
            print(f"DEBUG: System Instruction Length: {len(system_instruction)}")
            print(f"DEBUG: User Prompt Length: {len(user_prompt)}")

            message = self.client.messages.create(
                model=model_id,
                max_tokens=8192,
                system=system_instruction,
                tools=tools,
                tool_choice={"type": "tool", "name": tool_name},
                messages=[
                    {"role": "user", "content": user_prompt}
                ]
            )
            
            print(f"DEBUG: Anthropic Response received. Stop Reason: {message.stop_reason}")
            
            # Extract tool use
            for content in message.content:
                if content.type == "tool_use" and content.name == tool_name:
                    return content.input
            
            raise Exception("Anthropic did not use the tool.")
            
        except Exception as e:
            print(f"DEBUG: Anthropic Generation Error: {e}")
            raise Exception(f"Anthropic Generation Error: {e}")

    def simple_generate(self, model_id, system_instruction, user_prompt):
        message = self.client.messages.create(
            model=model_id,
            max_tokens=4096,
            system=system_instruction,
            messages=[
                {"role": "user", "content": user_prompt}
            ]
        )
        return message.content[0].text


class ModelManager:
    def __init__(self, config=None, base_dir=None, user_id=None, original_env=None, user_keys=None):
        self.config = config or {}
        self.original_env = original_env
        self.user_keys = user_keys or {}
        self.user_id = user_id
        
        self.base_dir = base_dir or os.getcwd()
        
        # User-Specific model config (Strict Isolation)
        if self.user_id:
            self.config_path = os.path.join(self.base_dir, 'state', 'users', self.user_id, 'model_config.json')
        else:
            self.config_path = os.path.join(self.base_dir, 'state', 'model_config.json')
        
        # Load keys - User Preferences > (Conditional) System Env
        def get_initial(name, user_key_type):
            # 1. User Preference (Highest Priority)
            val = self.user_keys.get(user_key_type)
            if val:
                return val

            # 2. System Environment (LOCAL MODE ONLY)
            if os.environ.get("ARBY_ALLOW_ENV_KEYS") == "true":
                val = os.environ.get(name)
                if not val or val == f"${{{name}}}": # Detect self-referencing shadow
                    if self.original_env and name in self.original_env:
                        return self.original_env[name]
                return val
            
            return None

        # Load keys
        self.keys = {
            "google": get_initial("GEMINI_API_KEY", "google"),
            "openai": get_initial("OPENAI_API_KEY", "openai"),
            "anthropic": get_initial("ANTHROPIC_API_KEY", "anthropic"),
            "xai": get_initial("XAI_API_KEY", "xai"),
        }
        
        # Initialize Providers
        self.providers = {}
        for provider_name, key_val in self.keys.items():
            if not key_val:
                continue
            
            resolved = self._resolve_key(key_val)
            if not resolved:
                continue
                
            try:
                if provider_name == "google":
                    self.providers["google"] = GeminiProvider(resolved)
                elif provider_name == "openai":
                    self.providers["openai"] = OpenAIProvider(resolved)
                elif provider_name == "anthropic":
                    self.providers["anthropic"] = AnthropicProvider(resolved)
                elif provider_name == "xai":
                    self.providers["xai"] = OpenAIProvider(resolved, base_url="https://api.x.ai/v1")
            except Exception as e:
                print(f"DEBUG: Error initializing {provider_name} Provider: {e}")

    def _resolve_key(self, key_string):
        if not key_string:
            return None
        
        # Helper to get from original or current env
        def get_env(name):
            if self.original_env and name in self.original_env:
                val = self.original_env[name]
                if val: return val
            return os.environ.get(name)
        
        # 1. Check for ${VAR} pattern - Explicit pointer
        import re
        match = re.search(r'\$\{(.+?)\}', key_string)
        if match:
            env_name = match.group(1)
            val = get_env(env_name)
            
            # If we got the SAME string back or it's empty or still a pointer, expansion failed
            if not val or val == key_string or val == f'${{{env_name}}}':
                 print(f"DEBUG: Resolution failed for pointer {key_string}")
                 return None
            return val

        # 2. Check if it's a direct environment variable name (pointer without ${})
        # Rules for being a pointer:
        # - All caps, numbers, underscore
        # - No special characters (like lowercase letters which often appear in raw keys)
        # - Exists in environment
        if key_string and re.match(r'^[A-Z0-9_]+$', key_string):
             val = get_env(key_string)
             if val and val != key_string:
                  return val
             
             # If it's all caps but NOT in env, check if it looks like a raw key
             # Gemini keys usually start with AIza... (which has lowercase, so it wouldn't match ^[A-Z0-9_]+$)
             # If it's something like 'OPENAI_KEY' but not in env, we should return None so UI shows 'Pointer not found'
             # If it's 'sk-...' it wouldn't match this regex anyway.
             
             # If it's a known raw key prefix that happens to be all caps, it's NOT a pointer
             if key_string.startswith("AI"): 
                  return key_string
             
             print(f"DEBUG: String '{key_string}' looks like a pointer but not found in env.")
             return None
            
        return key_string

    def save_config(self, config):
        with open(self.config_path, 'w') as f:
            json.dump(config, f, indent=4)

    def load_config(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return data
                    return {"custom_models": [], "hidden_ids": []}
            except Exception as e:
                print(f"DEBUG: Error loading model config at {self.config_path}: {e}")
                return {"custom_models": [], "hidden_ids": []}
        return {"custom_models": [], "hidden_ids": []}

    def _safe_float(self, val, default=0.0):
        if val is None or val == "":
            return default
        try:
            return float(val)
        except (ValueError, TypeError):
            return default

    def get_available_models(self):
        """Returns list of models with their locked status."""
        # Defaults
        defaults = [
            # Google
            {"id": "gemini-3-pro-preview", "name": "Gemini 3 Pro (Preview)", "provider": "google", "top_pick": True, "recommended": True, "description": "Deep Reasoning. The smartest model available.", "default_cost_in": 2.00, "default_cost_out": 12.00},
            {"id": "gemini-3-flash-preview", "name": "Gemini 3 Flash (Preview)", "provider": "google", "recommended": True, "description": "High Speed Agent. Smartest 'fast' model.", "default_cost_in": 0.50, "default_cost_out": 3.00},
            {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash", "provider": "google", "description": "The perfect balance of smarts & speed for Arby.", "default_cost_in": 0.30, "default_cost_out": 2.50},
            {"id": "gemini-2.5-flash-lite", "name": "Gemini 2.5 Flash-Lite", "provider": "google", "description": "Bulk Processing. Great for large PDF libraries.", "default_cost_in": 0.10, "default_cost_out": 0.40},
            {"id": "gemini-2.5-pro", "name": "Gemini 2.5 Pro", "provider": "google", "description": "Complex Logic. Use if Flash fails.", "default_cost_in": 1.25, "default_cost_out": 10.00},
            {"id": "gemini-2.0-flash", "name": "Gemini 2.0 Flash", "provider": "google", "description": "Reliability. The 'old reliable' from late 2025.", "default_cost_in": 0.10, "default_cost_out": 0.40},

            # Anthropic
            {"id": "claude-opus-4-5-20251101", "name": "Claude 4.5 Opus", "provider": "anthropic", "recommended": True, "top_pick": True, "description": "The absolute peak of Claude architecture.", "default_cost_in": 15.00, "default_cost_out": 75.00},
            {"id": "claude-sonnet-4-5-20250929", "name": "Claude 4.5 Sonnet", "provider": "anthropic", "recommended": True, "description": "Ultra-fast, ultra-smart creative partner.", "default_cost_in": 3.00, "default_cost_out": 15.00},
            {"id": "claude-haiku-4-5-20251001", "name": "Claude 4.5 Haiku", "provider": "anthropic", "description": "Fast and intelligent ultra-efficient model.", "default_cost_in": 0.25, "default_cost_out": 1.25},
            
            # OpenAI
            {"id": "gpt-5", "name": "GPT-5", "provider": "openai", "recommended": True, "top_pick": True, "description": "The current flagship from OpenAI.", "default_cost_in": 5.00, "default_cost_out": 15.00},
            {"id": "gpt-5-mini", "name": "GPT-5 Mini", "provider": "openai", "description": "Fast and smart miniature flagship.", "default_cost_in": 0.30, "default_cost_out": 1.20},
            {"id": "gpt-4.1", "name": "GPT-4.1", "provider": "openai", "description": "Reliable legacy flagship.", "default_cost_in": 2.50, "default_cost_out": 10.00},
            {"id": "gpt-4o", "name": "GPT-4o", "provider": "openai", "recommended": True, "description": "Standard multimodal model.", "default_cost_in": 2.50, "default_cost_out": 10.00},
            {"id": "o1", "name": "OpenAI o1", "provider": "openai", "description": "Reasoning & coding specialist.", "default_cost_in": 15.00, "default_cost_out": 60.00},
            {"id": "o3", "name": "OpenAI o3", "provider": "openai", "description": "Next-gen reasoning model.", "default_cost_in": 3.00, "default_cost_out": 12.00},
            {"id": "o3-mini", "name": "OpenAI o3-mini", "provider": "openai", "description": "Reasoning speedster.", "default_cost_in": 1.10, "default_cost_out": 4.40},
            {"id": "o4-mini", "name": "OpenAI o4-mini", "provider": "openai", "description": "Efficient next-gen reasoning.", "default_cost_in": 0.50, "default_cost_out": 2.00},
            
            # xAI
            {"id": "grok-4-1-fast-reasoning", "name": "Grok 4.1 Fast", "provider": "xai", "recommended": True, "top_pick": True, "description": "Advanced reasoning from xAI.", "default_cost_in": 5.00, "default_cost_out": 20.00},
            {"id": "grok-4-0709", "name": "Grok 4", "provider": "xai", "recommended": True, "description": "Latest xAI frontier model.", "default_cost_in": 5.00, "default_cost_out": 20.00},
            {"id": "grok-3", "name": "Grok 3", "provider": "xai", "description": "Stable Grok flagship.", "default_cost_in": 2.00, "default_cost_out": 10.00},
            {"id": "grok-3-mini", "name": "Grok 3 Mini", "provider": "xai", "description": "Efficient Grok model.", "default_cost_in": 0.50, "default_cost_out": 2.00},
            {"id": "grok-2-vision-1212", "name": "Grok 2 Vision", "provider": "xai", "description": "Visual intelligence from Grok.", "default_cost_in": 2.00, "default_cost_out": 10.00},
        ]
        
        config = self.load_config()
        
        # Filter hidden
        active_models = [m for m in defaults if m['id'] not in config.get('hidden_ids', [])]
        
        # Add Custom
        custom = config.get('custom_models', [])
        for c in custom:
            c['is_custom'] = True # Flag for UI to allow deletion
            active_models.append(c)
            
        # Enrich with Status and User Costs
        saved_costs = config.get('costs', {})
        health_status = config.get('health', {})
        core_model = config.get('core_model', 'gemini-2.5-flash') # Updated default to match new list

        for m in active_models:
            mid = m['id']
            # Locked Status
            provider = m["provider"]
            if provider == 'custom':
                 has_own_key = bool(m.get('api_key'))
                 has_default_key = bool(self.keys.get('openai'))
                 m["locked"] = not (has_own_key or has_default_key)
            else:
                m["locked"] = not bool(self.keys.get(provider))

            # Cost Rates
            cost_entry = saved_costs.get(mid, {})
            user_in = cost_entry.get('in') if isinstance(cost_entry, dict) else None
            user_out = cost_entry.get('out') if isinstance(cost_entry, dict) else None

            m['cost_in'] = self._safe_float(user_in, m.get('default_cost_in', 0.0))
            m['cost_out'] = self._safe_float(user_out, m.get('default_cost_out', 0.0))

            # Health Status
            m['health'] = health_status.get(mid, {"status": "unchecked"})
            
            # Dynamic Recommendation: Unrecommend if health is bad
            if m.get('recommended') and m['health']['status'] in ['rate_limit', 'auth_error', 'error']:
                m['recommended'] = False
            
            # DYNAMIC DEMOTION: If health is bad, remove recommendations
            if m['health']['status'] in ['error', 'auth_error']:
                m['recommended'] = False
                m['top_pick'] = False
                
            # Core and Sous Chef Flags
            if mid == core_model:
                m['is_core'] = True
            
            if mid == self.get_sous_chef_model_id():
                m['is_sous_chef'] = True
                
            if mid == self.get_librarian_model_id():
                m['is_librarian'] = True

        return active_models

    def set_core_model(self, model_id):
        config = self.load_config()
        config['core_model'] = model_id
        self.save_config(config)
        
    def get_core_model_id(self):
        config = self.load_config()
        return config.get('core_model', 'gemini-2.0-flash-exp')

    def set_sous_chef_model(self, model_id):
        config = self.load_config()
        config['sous_chef_model'] = model_id
        self.save_config(config)

    def get_sous_chef_model_id(self):
        config = self.load_config()
        # Default to 1.5 Flash for high reliability/quota if not set
        return config.get('sous_chef_model', 'gemini-1.5-flash')

    def set_librarian_model(self, model_id):
        config = self.load_config()
        config['librarian_model'] = model_id
        self.save_config(config)

    def get_librarian_model_id(self):
        config = self.load_config()
        # Default to 1.5 Flash - best for PDF ingestion
        return config.get('librarian_model', 'gemini-1.5-flash')

    def update_model_cost(self, model_id, cost_in, cost_out):
        config = self.load_config()
        if 'costs' not in config: config['costs'] = {}
        config['costs'][model_id] = {"in": cost_in, "out": cost_out}
        self.save_config(config)

    def _get_provider_for_model(self, model_id):
        models_list = self.get_available_models()
        target_model = next((m for m in models_list if m["id"] == model_id), None)
        
        if not target_model:
            raise ValueError(f"Unknown or hidden model: {model_id}")
            
        provider_name = target_model["provider"]
        provider = None
        
        if provider_name == 'custom':
            api_key = target_model.get('api_key') or self.keys['openai']
            base_url = target_model.get('base_url')
            if not api_key:
                 raise ValueError(f"No API Key found for custom model {model_id}")
            provider = OpenAIProvider(api_key=api_key, base_url=base_url)
        else:
            if provider_name not in self.providers:
                 raise ValueError(f"Provider {provider_name} is not configured.")
            provider = self.providers[provider_name]
            
        return provider

    def test_connection(self, model_id):
        print(f"Testing connectivity for {model_id}...")
        try:
            provider = self._get_provider_for_model(model_id)
            provider.ping(model_id)
            status = "ok"
            msg = "Connected"
        except Exception as e:
            status = "error"
            msg = str(e)
            print(f"DEBUG: Connection Test Failed for {model_id} - {e}")
            import traceback
            traceback.print_exc()
            msg_lower = msg.lower()
            if "429" in msg or "quota" in msg_lower or "resource_exhausted" in msg_lower:
                status = "rate_limit"
            elif "key" in msg_lower or "auth" in msg_lower or "401" in msg or "404" in msg or "not_found" in msg_lower:
                status = "auth_error"
            else:
                status = "error"
        
        # Save Result
        config = self.load_config()
        if 'health' not in config: config['health'] = {}
        
        # Format msg for UI display - keep it concise but informative
        display_msg = msg
        if len(display_msg) > 100:
            display_msg = display_msg[:97] + "..."

        config['health'][model_id] = {
            "status": status,
            "msg": display_msg,
            "last_checked": time.time()
        }
        self.save_config(config)
        return status, display_msg
        
    def add_custom_model(self, model_id, name, provider, base_url=None, api_key=None):
        config = self.load_config()
        new_model = {"id": model_id, "name": name, "provider": provider}
        
        if base_url: new_model["base_url"] = base_url
        if api_key: new_model["api_key"] = api_key
        
        # Avoid duplicates
        config['custom_models'] = [m for m in config.get('custom_models', []) if m['id'] != model_id]
        config['custom_models'].append(new_model)
        
        # Ensure it's not hidden
        if 'hidden_ids' in config and model_id in config['hidden_ids']:
            config['hidden_ids'].remove(model_id)
            
        self.save_config(config)
        
    def hide_model(self, model_id):
        config = self.load_config()
        
        # If it's custom, remove it entirely
        customs = config.get('custom_models', [])
        is_custom = any(m['id'] == model_id for m in customs)
        
        if is_custom:
            config['custom_models'] = [m for m in customs if m['id'] != model_id]
        else:
            # If default, add to hidden
            if 'hidden_ids' not in config: config['hidden_ids'] = []
            if model_id not in config['hidden_ids']:
                config['hidden_ids'].append(model_id)
                
        self.save_config(config)
        
    def restore_defaults(self):
        """Unhide all defaults. Keep customs?"""
        config = self.load_config()
        config['hidden_ids'] = []
        self.save_config(config)

    def generate(self, model_id, system_instruction, user_prompt, files=None, schema=WeeklyPlan):
        # 1. Identify Provider (Re-fetch to include dynamic ones)
        models_list = self.get_available_models()
        target_model = next((m for m in models_list if m["id"] == model_id), None)
        
        if not target_model:
            raise ValueError(f"Unknown or hidden model: {model_id}")
            
        provider_name = target_model["provider"]
        
        # CUSTOM PROVIDER LOGIC
        if provider_name == 'custom':
            api_key = target_model.get('api_key') or self.keys['openai'] # Fallback to OpenAI key if not provided
            base_url = target_model.get('base_url') # Can be None if standard OpenAI
            
            if not api_key:
                 raise ValueError(f"No API Key found for custom model {model_id}")
                 
            # Create ad-hoc provider
            # Assuming OpenAI compatible
            provider = OpenAIProvider(api_key=api_key, base_url=base_url)
        else:
            if provider_name not in self.providers:
                 raise ValueError(f"Provider {provider_name} is not configured (missing API key).")
            provider = self.providers[provider_name]
        
        # 2. Call Provider
        print(f"Generating structured response using {model_id} via {provider_name}...")
        return provider.generate(model_id, system_instruction, user_prompt, files, schema=schema)
