import os
import json
import sys
from datetime import datetime, timedelta, date, time as dt_time
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session
from functools import wraps
from dotenv import load_dotenv
import re
import threading
import schedule
import schedule
import time
import subprocess

# CAPTURE ORIGINAL SYSTEM ENVIRONMENT before load_dotenv shadows it
original_env = os.environ.copy()

# Ensure app modules are found
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from flask_login import LoginManager, login_user, logout_user, login_required, current_user

from app.core.agent import ArbyAgent
from app.core.inventory_manager import InventoryManager
from app.core.review_manager import ReviewManager
from app.core.user_manager import UserManager, User

load_dotenv()

app = Flask(__name__)
# Secret key needed for flash messages
app.secret_key = os.environ.get("FLASK_SECRET", "dev-secret-key-change-me")

# --- AUTH SETUP ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../'))
user_manager = UserManager(base_dir)

@login_manager.user_loader
def load_user(user_id):
    return user_manager.get_user(user_id)

# Set session duration (30 days)
app.config['REMEMBER_COOKIE_DURATION'] = timedelta(days=30)
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
login_manager.session_protection = "strong"

@app.context_processor
def inject_version():
    try:
        # Check for modifications
        status = subprocess.check_output(['git', 'status', '--porcelain'], stderr=subprocess.DEVNULL).decode('utf-8').strip()
        if status:
            git_hash = "modified"
        else:
            # Get short hash
            git_hash = subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD'], stderr=subprocess.DEVNULL).decode('utf-8').strip()
    except:
        git_hash = "local"
        
    return dict(app_version="v1.0.8", git_hash=git_hash)

# --- DYNAMIC AGENT HELPER ---
def get_agent():
    if not current_user.is_authenticated:
        return None
    # Provide a user-scoped agent
    return ArbyAgent(base_dir, user_id=current_user.id, original_env=original_env)

# --- AUTH ROUTES ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        remember = 'remember' in request.form
        user = user_manager.verify_login(email, password)
        if user:
            login_user(user, remember=remember)
            return redirect('/')
        else:
            flash('Invalid email or password', 'error')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        secret_key = request.form.get('secret_key')
        
        # Check registration secret
        reg_secret = os.environ.get("REGISTRATION_SECRET")
        if reg_secret and secret_key != reg_secret:
            flash('Invalid registration key', 'error')
            return render_template('signup.html')
        
        user, error = user_manager.create_user(name, email, password)
        if user:
            login_user(user)
            flash('Welcome to Arby!', 'success')
            return redirect('/')
        else:
            flash(error, 'error')
    return render_template('signup.html')

# --- ADMIN ACCESS ---
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('is_admin'):
            flash('Admin access required', 'error')
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        password = request.form.get('password')
        if password == os.environ.get("ADMIN_PASSWORD"):
            session['is_admin'] = True
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid administrator password', 'error')
    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('is_admin', None)
    return redirect(url_for('login'))

@app.route('/admin')
@admin_required
def admin_dashboard():
    users = user_manager.load_users()
    user_stats = []
    for u in users:
        usage = user_manager.get_user_storage_usage(u.id)
        user_stats.append({
            'user': u,
            'usage_mb': round(usage, 2),
            'limit_mb': u.storage_limit_mb
        })
    return render_template('admin.html', user_stats=user_stats)

@app.route('/admin/user/<user_id>/wipe', methods=['POST'])
@admin_required
def admin_wipe_user(user_id):
    success, error = user_manager.wipe_user_data(user_id)
    if success:
        flash(f'Cleaned all data for user {user_id}', 'success')
    else:
        flash(f'Wipe failed: {error}', 'error')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/user/<user_id>/delete', methods=['POST'])
@admin_required
def admin_delete_user(user_id):
    if user_manager.delete_user(user_id):
        flash(f'Permanently deleted user {user_id}', 'success')
    else:
        flash(f'Deletion failed', 'error')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/user/<user_id>/limit', methods=['POST'])
@admin_required
def admin_set_limit(user_id):
    limit = request.form.get('limit_mb')
    if limit and user_manager.set_user_storage_limit(user_id, limit):
        flash(f'Updated storage limit for user {user_id}', 'success')
    else:
        flash(f'Limit update failed', 'error')
    return redirect(url_for('admin_dashboard'))

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/manifest.json')
def manifest():
    return app.send_static_file('manifest.json')

# --- SCHEDULER (Disabled for now in multi-user refactor) ---
# Todo: Implement per-user scheduling
def init_scheduler():
    pass 




# Helper for display
def format_date_suffix(dt):
    if not dt: return "Not Scheduled"
    suffix = "th" if 11 <= dt.day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(dt.day % 10, "th")
    # %p returns AM/PM, using abbreviated month for space
    return dt.strftime(f"%A, %b {dt.day}{suffix} at %I:%M %p").replace("AM", "am").replace("PM", "pm")

@app.template_filter('pretty_date')
def pretty_date_filter(date_str):
    if not date_str:
        return ""
    try:
        # Assuming date_str is YYYY-MM-DD
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        suffix = "th" if 11 <= dt.day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(dt.day % 10, "th")
        return dt.strftime(f"%A - %b {dt.day}{suffix}")
    except Exception:
        return date_str

@app.template_filter('day_name')
def day_name_filter(date_str):
    if not date_str: return ""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%A")
    except:
        return date_str

@app.template_filter('short_date')
def short_date_filter(date_str):
    if not date_str: return ""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        suffix = "th" if 11 <= dt.day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(dt.day % 10, "th")
        return dt.strftime(f"%b {dt.day}{suffix}")
    except:
        return date_str

@app.context_processor
def inject_common_data():
    """Provides common data to all templates globally."""
    agent = get_agent()
    if not agent:
        return dict(prefs={})
        
    # Load Prefs
    pref_path = agent.pref_file
    prefs = {}
    if os.path.exists(pref_path):
        try:
            with open(pref_path, 'r') as f:
                prefs = json.load(f)
        except:
            pass
    
    # Ensure data_context exists for safety
    if 'data_context' not in prefs:
        prefs['data_context'] = {}
            
    # Load Ideas
    current_ideas = ""
    if os.path.exists(agent.ideas_file):
        try:
            with open(agent.ideas_file, 'r') as f:
                current_ideas = f.read().strip()
        except:
            pass
            
    return dict(prefs=prefs, current_ideas=current_ideas)

# --- ROUTES ---
@app.route('/')
@login_required
def index():
    try:
        agent = get_agent()
        
        # Load Config
        config = agent.calendar_manager.load_config()
        schedule_enabled = config.get('schedule_enabled', True)

        # Pass necessary data to dashboard
        next_run_dt = agent.calendar_manager.get_next_run_dt()
        next_run_str = format_date_suffix(next_run_dt) if schedule_enabled and next_run_dt else "Not Scheduled"
        
        # Simple history view
        history = agent.load_history()
        
        last_run_display = "Never"
        if history:
             try:
                 # Assuming ISO format with time "2024-01-01T10:00:00"
                 dt = datetime.fromisoformat(history[-1]['date'])
                 last_run_display = format_date_suffix(dt)
             except:
                 last_run_display = history[-1]['date'] # Fallback to raw string if parse fails
     
        last_run = last_run_display
        
        # Get Models for Selector
        available_models = agent.model_manager.get_available_models()
        
        # Identify Current Head Chef
        current_model = next((m for m in available_models if m.get('is_core')), None)
        if not current_model:
            current_model = next((m for m in available_models if not m.get('locked')), None)

        # Identifiers for next 14 days
        days_data = []
        base = datetime.now()
        for i in range(14):
            d = base + timedelta(days=i)
            days_data.append({
                "day": d.strftime("%Y-%m-%d"),
                "label": f"{d.strftime('%A')} ({d.strftime('%b %d')})"
            })

        # Default Start Date Logic
        next_run_ref = next_run_dt or datetime.now()
        default_start = agent.calendar_manager.get_default_start_date(next_run_ref)
        if default_start < date.today():
            default_start = date.today()
            
        default_start_iso = default_start.strftime("%Y-%m-%d")
        default_start_pretty = default_start.strftime("%A, %b %d")

        # Load Prefs for modal
        pref_path = agent.pref_file
        prefs = {}
        if os.path.exists(pref_path):
            with open(pref_path, 'r') as f:
                prefs = json.load(f)

        # Defaults to prevent Jinja errors
        if 'data_context' not in prefs:
            prefs['data_context'] = {
                "use_inventory": True,
                "use_history": True,
                "use_ideas": True,
                "use_cookbook": True
            }
        else:
            for k, v in {"use_inventory": True, "use_history": True, "use_ideas": True, "use_cookbook": True}.items():
                if k not in prefs['data_context']:
                    prefs['data_context'][k] = v

        if 'email_settings' not in prefs: prefs['email_settings'] = {}
        if 'history_depth' not in prefs: prefs['history_depth'] = 50
        if 'long_term_preferences' not in prefs: prefs['long_term_preferences'] = ""

        # Recipe Ideas for modal
        current_ideas = ""
        if os.path.exists(agent.ideas_file):
            with open(agent.ideas_file, 'r') as f:
                current_ideas = f.read().strip()

        active_plan_exists = agent.calendar_manager.active_plan_exists()

        return render_template('index.html', 
                               next_run=next_run_str, 
                               last_run=last_run, 
                               models=available_models, 
                               current_model=current_model if current_model else {"name": "No Active Chef", "id": "none"},
                               default_start_date=default_start_iso,
                               schedule_enabled=schedule_enabled,
                               active_plan_exists=active_plan_exists,
                               run_day=config.get('run_day', 'Sunday'),
                               run_time=config.get('run_time', '10:00'),
                               duration_days=config.get('duration_days', 8),
                               days_data=days_data,
                               default_start_date_pretty=default_start_pretty,
                               today_iso=datetime.now().strftime("%Y-%m-%d"),
                               prefs=prefs,
                               current_ideas=current_ideas,
                               user=current_user)

    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"CRITICAL DASHBOARD ERROR: {e}\n{error_details}")
        return f"Arby Dashboard Error: {str(e)}<br><br><pre>{error_details}</pre>", 500


@app.route('/health')
def health_check():
    """Simple health check for monitoring scripts."""
    return {"status": "healthy", "version": "1.0.0"}

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings_page():
    agent = get_agent()

    if request.method == 'POST':
        # Now saving API keys to user-specific prefs.json instead of global .env
        keys_to_update = {
            "google": request.form.get("gemini_key"),
            "openai": request.form.get("openai_key"),
            "anthropic": request.form.get("anthropic_key"),
            "xai": request.form.get("xai_key"),
        }
        
        try:
            pref_path = agent.pref_file
            prefs = {}
            if os.path.exists(pref_path):
                with open(pref_path, 'r') as f:
                    prefs = json.load(f)
            
            if 'api_keys' not in prefs:
                prefs['api_keys'] = {}
            
            for k, v in keys_to_update.items():
                if v and v.strip() != "***":
                    val = v.strip()
                    # Check if it's a pointer to an env var (User wants to use system env for themselves)
                    is_pointer = False
                    # Check if it matches an env var in current or original env
                    if (original_env and val in original_env and original_env[val]) or (os.environ.get(val)):
                        is_pointer = True
                    
                    if is_pointer and not val.startswith("${"):
                        val = f'${{{val}}}'
                    
                    prefs['api_keys'][k] = val
                elif v == "": # User explicitly cleared it (will now fallback to system)
                    if k in prefs['api_keys']:
                        del prefs['api_keys'][k]
            
            with open(pref_path, 'w') as f:
                json.dump(prefs, f, indent=4)
                
            flash("Settings updated! API keys are now stored in your private preferences.", "success")
        except Exception as e:
            flash(f"Error saving settings: {e}", "error")
        return redirect('/settings')

    # GET
    # Fetch all models (including status) for management UI
    all_models = agent.model_manager.get_available_models()
    
    # Load Preferences
    pref_path = agent.pref_file
    prefs = {}
    if os.path.exists(pref_path):
        with open(pref_path, 'r') as f:
            prefs = json.load(f)
    
    # Default data context if missing
    if 'data_context' not in prefs:
        prefs['data_context'] = {
            "use_inventory": True,
            "use_history": True,
            "use_ideas": True,
            "use_cookbook": True
        }
    else:
        for k, v in {"use_inventory": True, "use_history": True, "use_ideas": True, "use_cookbook": True}.items():
            if k not in prefs['data_context']:
                prefs['data_context'][k] = v

    if 'email_settings' not in prefs:
        prefs['email_settings'] = {}
        
    if 'history_depth' not in prefs:
        prefs['history_depth'] = 50
        
    if 'long_term_preferences' not in prefs:
        prefs['long_term_preferences'] = ""

    # API Key Context for UI
    system_env = {}
    env_path = os.path.join(base_dir, '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                if '=' in line and not line.startswith('#'):
                    k, v = line.split('=', 1)
                    system_env[k.strip()] = v.strip().strip('"').strip("'")
    
    key_types = {
        "google": "GEMINI_API_KEY",
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "xai": "XAI_API_KEY",
    }
    
    user_keys = prefs.get('api_keys', {})
    display_keys = {}
    
    for k, env_name in key_types.items():
        user_val = user_keys.get(k)
        system_val = system_env.get(env_name, "")
        
        # Determine source and value
        source = "User Specific" if user_val else "System Default"
        raw_val = user_val if user_val else system_val
        
        # Resolve pointer logic
        pure_var = raw_val
        match = re.search(r'\$\{(.+?)\}', raw_val)
        if match:
            pure_var = match.group(1)
        
        # Check if it's already in the process environment
        is_env_present = bool(os.environ.get(pure_var))
        # Or if it looks like a pointer (all caps/underscores, etc.)
        is_pointer_style = pure_var and re.match(r'^[A-Z0-9_]+$', pure_var) and len(pure_var) < 64
        if is_pointer_style and pure_var.startswith("AI"):
             is_pointer_style = False # Likely a raw Gemini key
        
        is_pointer = is_env_present or is_pointer_style
        resolved = agent.model_manager._resolve_key(raw_val) if raw_val else None
        
        status_msg = ""
        if is_pointer and not resolved:
            status_msg = f"Pointer '{pure_var}' not found"
        
        display_keys[k] = {
            "val": pure_var if (is_pointer or not raw_val) else "***",
            "active": bool(resolved),
            "status": status_msg,
            "source": source if raw_val else None
        }

    # Recipe Ideas for Data Tab
    current_ideas = ""
    if os.path.exists(agent.ideas_file):
        with open(agent.ideas_file, 'r') as f:
            current_ideas = f.read().strip()

    return render_template('settings.html', 
        display_keys=display_keys,
        models=all_models,
        pdf_library_path=agent.cookbook_manager.library_path,
        state_folder_path=agent.user_state_dir,
        env_file_path=os.path.join(base_dir, '.env'),
        prefs=prefs,
        current_ideas=current_ideas,
        active_tab=request.args.get('tab', 'models'),
        user=current_user
    )

@app.route('/help')
def help_page():
    return render_template('help.html')

@app.route('/settings/preferences', methods=['POST'])
@login_required
def update_preferences():
    agent = get_agent()
    pref_path = agent.pref_file
    prefs = {}
    if os.path.exists(pref_path):
        with open(pref_path, 'r') as f:
            prefs = json.load(f)
            
    # Update Data Context
    prefs['data_context'] = {
        "use_inventory": 'use_inventory' in request.form,
        "use_history": 'use_history' in request.form,
        "use_ideas": True, # Always true if text box exists
        "use_cookbook": 'use_cookbook' in request.form,
    }
    
    # Update History Depth
    prefs['history_depth'] = int(request.form.get('history_depth', 50))
    
    # Update Long-term Preferences
    prefs['long_term_preferences'] = request.form.get('long_term_preferences', '')
    
    # Update Recipes Ideas
    ideas = request.form.get('ideas', '')
    if ideas is not None:
        with open(agent.ideas_file, 'w') as f:
            f.write(ideas.strip())
            
    with open(pref_path, 'w') as f:
        json.dump(prefs, f, indent=4)
        
    flash("Chef's Brain updated!", "success")
    return redirect('/settings?tab=data')

@app.route('/settings/data/delete', methods=['POST'])
@login_required
def delete_data():
    agent = get_agent()
    target = request.form.get('target')
    
    try:
        if target == 'pantry':
             agent.inventory_manager.save_inventory([])
             flash("Pantry has been cleared.", "success")
        elif target == 'library':
             # Clear recipes file
             with open(agent.cookbook_manager.recipes_file, 'w') as f:
                 json.dump([], f)
             flash("Library has been cleared.", "success")
        elif target == 'history':
             agent.save_history([])
             flash("Meal history has been cleared.", "success")
        elif target == 'all':
             agent.inventory_manager.save_inventory([])
             with open(agent.cookbook_manager.recipes_file, 'w') as f:
                 json.dump([], f)
             agent.save_history([])
             # Clear Ideas too
             with open(agent.ideas_file, 'w') as f:
                 f.write("")
             flash("ALL data has been wiped.", "success")
        else:
            flash("Invalid deletion target.", "error")
            
    except Exception as e:
        flash(f"Deletion failed: {e}", "error")
        
    return redirect('/settings?tab=data')

@app.route('/settings/account/update', methods=['POST'])
@login_required
def update_account():
    name = request.form.get('name')
    email = request.form.get('email')
    password = request.form.get('password')
    
    if not name or not email:
        flash("Name and Email are required.", "error")
        return redirect('/settings?tab=account')
        
    user, error = user_manager.update_user(current_user.id, name=name, email=email, password=password if password else None)
    
    if error:
        flash(error, "error")
    else:
        # Re-login with updated user object
        login_user(user)
        flash("Account details updated successfully!", "success")
        
    return redirect('/settings?tab=account')

@app.route('/settings/account/delete', methods=['POST'])
@login_required
def delete_account():
    confirmation = request.form.get('confirmation')
    if confirmation != 'DELETE':
         flash("Please type DELETE to confirm account deletion.", "error")
         return redirect('/settings?tab=account')
         
    success = user_manager.delete_user(current_user.id)
    if success:
        logout_user()
        flash("Your account has been permanently deleted.", "success")
        return redirect('/')
    else:
        flash("Failed to delete account.", "error")
        return redirect('/settings?tab=account')

@app.route('/settings/notifications', methods=['POST'])
@login_required
def update_notifications():
    agent = get_agent()
    pref_path = agent.pref_file
    
    prefs = {}
    if os.path.exists(pref_path):
        with open(pref_path, 'r') as f:
            prefs = json.load(f)
            
    raw_sender = request.form.get('sender_email', '').strip()
    raw_pass = request.form.get('app_password', '').strip()
    
    def auto_pointer(val):
        if not val: return val
        # Check if matches env var
        if (original_env and val in original_env and original_env[val]) or (os.environ.get(val)):
            if not val.startswith("${"):
                return f"${{{val}}}"
        return val

    prefs['email_settings'] = {
        "sender": auto_pointer(raw_sender),
        "password": auto_pointer(raw_pass),
        "receivers": request.form.get('receiver_emails')
    }
    
    with open(pref_path, 'w') as f:
        json.dump(prefs, f, indent=4)
        
    flash("Notification settings updated! Pointers resolved if used.", "success")
    return redirect('/settings?tab=notifications')

@app.route('/settings/models/add', methods=['POST'])
@login_required
def add_custom_model():
    agent = get_agent()
    provider = request.form.get('provider')
    model_id = request.form.get('model_id')
    name = request.form.get('name')
    base_url = request.form.get('base_url')
    api_key = request.form.get('api_key')
    
    if provider and model_id and name:
        agent.model_manager.add_custom_model(model_id, name, provider, base_url, api_key)
        flash(f"Added custom model: {name}", "success")
    else:
        flash("Missing details.", "error")
        
    return redirect('/settings')

@app.route('/settings/models/delete', methods=['POST'])
@login_required
def delete_model():
    agent = get_agent()
    model_id = request.form.get('model_id')
    if model_id:
        agent.model_manager.hide_model(model_id)
        flash("Model removed from list.", "info")
    return redirect('/settings')


@app.route('/settings/models/restore', methods=['POST'])
@login_required
def restore_models():
    agent = get_agent()
    agent.model_manager.restore_defaults()
    flash("Restored all default models.", "success")
    return redirect('/settings')

@app.route('/pantry')
@login_required
def pantry_page():
    agent = get_agent()
    # Sort by expiry if possible or just as is
    items = agent.inventory_manager.load_inventory()
    return render_template('inventory.html', items=enumerate(items), user=current_user)

@app.route('/pantry/add', methods=['POST'])
@login_required
def add_inventory():
    agent = get_agent()
    raw_text = request.form.get('ingredients')
    if raw_text:
        try:
            count = agent.inventory_manager.parse_and_add(raw_text)
            if count > 0:
                flash(f"Successfully added {count} items to pantry!", "success")
            else:
                flash("Could not parse items. Please try again or check your API quota.", "error")
        except Exception as e:
            flash(f"Error: {e}", "error")
    return redirect(url_for('pantry_page'))
    
@app.route('/pantry/delete/<int:index>', methods=['POST'])
@login_required
def delete_inventory(index):
    agent = get_agent()
    if agent.inventory_manager.delete_item(index):
        flash("Item removed from pantry.", "info")
    else:
        flash("Failed to remove item.", "error")
    return redirect(url_for('pantry_page'))

@app.route('/pantry/edit/<int:index>', methods=['POST'])
@login_required
def edit_inventory(index):
    agent = get_agent()
    data = {
        "item": request.form.get("item"),
        "brand": request.form.get("brand"),
        "quantity": float(request.form.get("quantity") or 0),
        "unit": request.form.get("unit"),
        "size_value": float(request.form.get("size_value") or 0) if request.form.get("size_value") else None,
        "size_unit": request.form.get("size_unit"),
        "purchase_date": request.form.get("purchase_date"),
        "expiry_date": request.form.get("expiry_date"),
    }
    if agent.inventory_manager.update_item(index, data):
        flash("Pantry item updated.", "success")
    else:
        flash("Failed to update item.", "error")
    return redirect(url_for('pantry_page'))

@app.route('/pantry/increment/<int:index>', methods=['POST'])
@login_required
def increment_inventory(index):
    agent = get_agent()
    items = agent.inventory_manager.load_inventory()
    if 0 <= index < len(items):
        items[index]['quantity'] += 1
        items[index]['updated_on'] = datetime.now().strftime("%Y-%m-%d")
        agent.inventory_manager.save_inventory(items)
        return jsonify({"status": "ok", "new_quantity": items[index]['quantity']})
    return jsonify({"status": "error"}), 404

@app.route('/history')
@login_required
def history_page():
    agent = get_agent()
    history = agent.load_history()
    # Reverse to show newest first, but keep original indices for actions
    indexed_history = list(enumerate(history))
    indexed_history.reverse()
    return render_template('history.html', history=indexed_history, user=current_user)

@app.route('/history/delete/<int:index>', methods=['POST'])
@login_required
def delete_history_entry(index):
    agent = get_agent()
    history = agent.load_history()
    if 0 <= index < len(history):
        history.pop(index)
        with open(agent.history_file, 'w') as f:
            json.dump(history, f, indent=4)
        flash("History entry removed.", "info")
    return redirect('/history')

@app.route('/history/review/<int:index>', methods=['POST'])
@login_required
def review_history_entry(index):
    agent = get_agent()
    feedback = request.form.get('feedback')
    history = agent.load_history()
    
    if 0 <= index < len(history):
        entry = history[index]
        try:
            # Re-construct a plan-like object or just use the summary text
            plan_text = entry.get('summary', '')
            # If we have meal details, include them for better extraction
            if 'meals' in entry:
                plan_text += "\n\nMeals in this plan:\n"
                for m in entry['meals']:
                    plan_text += f"- {m['name']} (Rating: {m.get('rating', 'None')})\n"
            
            result_msg = agent.review_manager.process_feedback(plan_text, feedback)
            flash(result_msg, "success")
        except Exception as e:
            print(f"Failed to process history feedback: {e}")
            flash("Submitted feedback.", "info")
            
    return redirect('/history')

@app.route('/history/rate/<int:index>/<int:meal_index>/<int:rating>', methods=['POST'])
@login_required
def rate_history_meal(index, meal_index, rating):
    agent = get_agent()
    history = agent.load_history()
    
    if 0 <= index < len(history):
        entry = history[index]
        if 'meals' in entry and 0 <= meal_index < len(entry['meals']):
            entry['meals'][meal_index]['rating'] = rating
            
            # Also sync to cookbook if possible
            meal_name = entry['meals'][meal_index]['name']
            agent.cookbook_manager.update_recipe_rating_by_name(meal_name, rating)
            
            with open(agent.history_file, 'w') as f:
                json.dump(history, f, indent=4)
            flash(f"Rated {meal_name} {rating} stars!", "success")
            
    return redirect('/history')

@app.route('/generate', methods=['POST'])
@login_required
def generate_plan():
    agent = get_agent()
    """Generates a DRAFT plan and redirects to review page."""
    model_id = request.form.get('model_id')
    start_date = request.form.get('start_date')
    
    # Enforce no past start dates
    if start_date:
        try:
            today = date.today()
            sd_obj = datetime.strptime(start_date, "%Y-%m-%d").date()
            if sd_obj < today:
                start_date = today.strftime("%Y-%m-%d")
        except:
            pass
            
    duration = request.form.get('duration')
    
    # Enforce 7-day limit
    if duration:
        try:
            duration = min(int(duration), 7)
        except:
            duration = 4
    else:
        duration = 4
    
    # Persist Preference & Context Overrides
    try:
        pref_path = agent.pref_file
        prefs = {}
        if os.path.exists(pref_path):
            with open(pref_path, 'r') as f:
                prefs = json.load(f)
        
        # Update Model Preference
        if model_id:
            prefs['preferred_model'] = model_id
        
        # Update Data Context from modal overrides
        prefs['data_context'] = {
            "use_inventory": 'use_inventory' in request.form,
            "use_history": 'use_history' in request.form,
            "use_ideas": True,
            "use_cookbook": 'use_cookbook' in request.form,
        }
        
        # Update History Depth
        history_depth = request.form.get('history_depth')
        if history_depth:
            prefs['history_depth'] = int(history_depth)
        
        # Update Long-term Preferences
        ltp = request.form.get('long_term_preferences')
        if ltp is not None:
            prefs['long_term_preferences'] = ltp
        
        # Update Recipe Ideas from modal
        modal_ideas = request.form.get('ideas')
        if modal_ideas is not None:
             with open(agent.ideas_file, 'w') as f:
                 f.write(modal_ideas.strip())
        
        with open(pref_path, 'w') as f:
            json.dump(prefs, f, indent=4)
    except Exception as e:
        print(f"Failed to save context: {e}")

    try:
        draft = agent.generate_draft(model_id=model_id, start_date=start_date, duration=duration)
        if "error" in draft:
            flash(f"Error: {draft['error']}", "error")
            return redirect('/')
            
        # Save Draft to State
        draft_path = os.path.join(agent.user_state_dir, 'current_draft.json')
        with open(draft_path, 'w') as f:
            json.dump(draft, f, indent=4)
            
        return redirect('/plan/review')
    except Exception as e:
        print(f"Error generating: {e}")
        flash(f"Error generating plan: {str(e)}", "error")
        return redirect('/')

@app.route('/plan/review')
@login_required
def review_plan_page():
    agent = get_agent()
    draft_path = os.path.join(agent.user_state_dir, 'current_draft.json')
    if not os.path.exists(draft_path):
        flash("No draft plan found. Please generate one first.", "warning")
        return redirect('/')
        
    with open(draft_path, 'r') as f:
        draft = json.load(f)
        
    return render_template('review_plan.html', plan=draft, user=current_user)

@app.route('/plan/modify', methods=['POST'])
@login_required
def modify_plan():
    agent = get_agent()
    user_feedback = request.form.get('feedback')
    model_id = request.form.get('model_id') # Optional override
    
    draft_path = os.path.join(agent.user_state_dir, 'current_draft.json')
    if not os.path.exists(draft_path):
        flash("No draft found to modify.", "error")
        return redirect('/')
        
    with open(draft_path, 'r') as f:
        current_draft = json.load(f)
        
    if not user_feedback:
        flash("Please provide feedback.", "warning")
        return redirect('/plan/review')
        
    # Resolve Model ID based on Chef selection
    chef_type = request.form.get('chef', 'main')
    if chef_type == 'sous':
        model_id = agent.model_manager.get_sous_chef_model_id()
    else:
        model_id = agent.model_manager.get_core_model_id()

    # Execute Modification
    new_draft = agent.modify_plan(current_draft, user_feedback, model_id=model_id)
    
    if "error" in new_draft:
        flash(f"Modification failed: {new_draft['error']}", "error")
        return redirect('/plan/review')
        
    # Save New Draft
    with open(draft_path, 'w') as f:
        json.dump(new_draft, f, indent=4)
        
    flash("Plan updated based on your feedback!", "success")
    return redirect('/plan/review')

@app.route('/plan/active/modify', methods=['POST'])
@login_required
def modify_active_plan():
    agent = get_agent()
    user_feedback = request.form.get('feedback')
    
    active_path = os.path.join(agent.user_state_dir, 'active_plan.json')
    if not os.path.exists(active_path):
        flash("No active plan found to modify.", "error")
        return redirect('/')
        
    with open(active_path, 'r') as f:
        current_plan = json.load(f)
        
    if not user_feedback:
        flash("Please provide feedback.", "warning")
        return redirect('/plan/view')
        
    # Resolve Model ID based on Chef selection
    chef_type = request.form.get('chef', 'main')
    if chef_type == 'sous':
        model_id = agent.model_manager.get_sous_chef_model_id()
    else:
        model_id = agent.model_manager.get_core_model_id()

    # Execute Modification
    # We pass the current plan. The agent will return a NEW plan structure.
    new_plan = agent.modify_plan(current_plan, user_feedback, model_id=model_id)
    
    if "error" in new_plan:
        flash(f"Modification failed: {new_plan['error']}", "error")
        return redirect('/plan/view')
    
    # Preserve existing state
    if 'checked_groceries' in current_plan:
        new_plan['checked_groceries'] = current_plan['checked_groceries']
    if 'completed_meals' in current_plan:
        new_plan['completed_meals'] = current_plan['completed_meals']
        
    # We might want to re-run pantry recommendations since ingredients changed
    try:
        recommendations = agent.recommend_grocery_checks(new_plan)
        new_plan['pantry_recommendations'] = recommendations
    except:
        pass
        
    # Save New Active Plan
    with open(active_path, 'w') as f:
        json.dump(new_plan, f, indent=4)
        
    # UPDATE CALENDAR (Sync)
    try:
        calendar_update = {}
        existing_calendar = agent.calendar_manager.load_calendar()
        
        for day in new_plan['days']:
            date_str = day['date']
            day_state = existing_calendar.get(date_str, {}).copy()
            if day.get('breakfast'): day_state['breakfast'] = day['breakfast']['name']
            if day.get('lunch'): day_state['lunch'] = day['lunch']['name']
            if day.get('dinner'): day_state['dinner'] = day['dinner']['name']
            calendar_update[date_str] = day_state
            
        agent.calendar_manager.update_calendar(calendar_update)
    except Exception as e:
        print(f"Failed to sync calendar after modify: {e}")

    flash("Active plan updated!", "success")
    return redirect('/plan/view')

@app.route('/plan/confirm', methods=['POST'])
@login_required
def confirm_plan():
    agent = get_agent()
    draft_path = os.path.join(agent.user_state_dir, 'current_draft.json')
    if not os.path.exists(draft_path):
        return redirect('/')
        
    with open(draft_path, 'r') as f:
        draft = json.load(f)
    
    # Finalize
    agent.finalize_plan(draft)
    
    # Auto-run Pantry Check
    try:
        recommendations = agent.recommend_grocery_checks(draft)
        draft['pantry_recommendations'] = recommendations
    except Exception as e:
        print(f"Auto-pantry check failed: {e}")
    
    # Move to Active Plan
    active_path = os.path.join(agent.user_state_dir, 'active_plan.json')
    with open(active_path, 'w') as f:
        json.dump(draft, f, indent=4)
        
    # Remove Draft
    os.remove(draft_path)
    
    # Clear Ideas/Cravings
    if os.path.exists(agent.ideas_file):
        with open(agent.ideas_file, 'w') as f:
            f.write("")
    
    flash("Plan confirmed! Calendar updated and email sent.", "success")
    return redirect('/plan/view')

@app.route('/plan/view')
@login_required
def view_active_plan():
    agent = get_agent()
    active_path = os.path.join(agent.user_state_dir, 'active_plan.json')
    if not os.path.exists(active_path):
         flash("No active detailed plan found.", "info")
         return redirect('/')
         
    with open(active_path, 'r') as f:
        plan = json.load(f)
        
    # Enrich plan with current cookbook ratings
    recipes = agent.cookbook_manager.load_recipes()
    recipe_map = {r['name'].lower(): r for r in recipes}
    
    for day in plan.get('days', []):
        for mt in ['breakfast', 'lunch', 'dinner']:
            meal = day.get(mt)
            if meal and meal.get('name'):
                match = recipe_map.get(meal['name'].lower())
                if match:
                    meal['recipe_id'] = match['id']
                    # Keep plan rating if already set, else use library rating
                    if 'rating' not in meal:
                        meal['rating'] = match.get('rating', 0)
    
    return render_template('view_plan.html', plan=plan, title="Meal Plan", user=current_user)

@app.route('/plan/grocery')
@login_required
def grocery_plan_page():
    agent = get_agent()
    active_path = os.path.join(agent.user_state_dir, 'active_plan.json')
    if not os.path.exists(active_path):
          flash("No active detailed plan found.", "info")
          return redirect('/')
          
    with open(active_path, 'r') as f:
        plan = json.load(f)
        
    return render_template('grocery_list.html', plan=plan, title="Grocery List", user=current_user)

@app.route('/plan/cook')
@login_required
def cook_plan_page():
    agent = get_agent()
    active_path = os.path.join(agent.user_state_dir, 'active_plan.json')
    if not os.path.exists(active_path):
          flash("No active detailed plan found.", "info")
          return redirect('/')
          
    with open(active_path, 'r') as f:
        plan = json.load(f)
    
    return render_template('cooking_mode.html', plan=plan, title="Live Cooking", user=current_user)

@app.route('/api/plan/grocery/toggle_meal', methods=['POST'])
@login_required
def toggle_grocery_meal_item():
    agent = get_agent()
    data = request.json
    item_id = data.get('item_id') # format: date-meal-index
    
    active_path = os.path.join(agent.user_state_dir, 'active_plan.json')
    if not os.path.exists(active_path):
        return jsonify({"status": "error", "message": "No active plan"}), 404
        
    try:
        with open(active_path, 'r') as f:
            plan = json.load(f)
            
        # Use a dict for checked groceries: { "item_id": True/False }
        if 'checked_groceries' not in plan:
            plan['checked_groceries'] = {}
            
        current_state = plan['checked_groceries'].get(item_id, False)
        new_state = not current_state
        plan['checked_groceries'][item_id] = new_state
            
        with open(active_path, 'w') as f:
            json.dump(plan, f, indent=4)
            
        return jsonify({"status": "ok", "checked": new_state})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/plan/cook/toggle_ingredient', methods=['POST'])
@login_required
def toggle_cooking_ingredient():
    agent = get_agent()
    data = request.json
    item_id = data.get('item_id') # format: date-meal-index
    
    active_path = os.path.join(agent.user_state_dir, 'active_plan.json')
    if not os.path.exists(active_path):
        return jsonify({"status": "error", "message": "No active plan"}), 404
        
    try:
        with open(active_path, 'r') as f:
            plan = json.load(f)
            
        if 'checked_cooking_ingredients' not in plan:
            plan['checked_cooking_ingredients'] = {}
            
        current_state = plan['checked_cooking_ingredients'].get(item_id, False)
        new_state = not current_state
        plan['checked_cooking_ingredients'][item_id] = new_state
            
        with open(active_path, 'w') as f:
            json.dump(plan, f, indent=4)
            
        return jsonify({"status": "ok", "checked": new_state})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/plan/cook/toggle_step', methods=['POST'])
@login_required
def toggle_cooking_step():
    agent = get_agent()
    data = request.json
    step_id = data.get('step_id') # format: date-meal-stepindex
    
    active_path = os.path.join(agent.user_state_dir, 'active_plan.json')
    if not os.path.exists(active_path):
        return jsonify({"status": "error", "message": "No active plan"}), 404
        
    try:
        with open(active_path, 'r') as f:
            plan = json.load(f)
            
        if 'completed_cooking_steps' not in plan:
            plan['completed_cooking_steps'] = {}
            
        current_state = plan['completed_cooking_steps'].get(step_id, False)
        new_state = not current_state
        plan['completed_cooking_steps'][step_id] = new_state
            
        with open(active_path, 'w') as f:
            json.dump(plan, f, indent=4)
            
        return jsonify({"status": "ok", "completed": new_state})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/plan/cook/toggle_meal', methods=['POST'])
@login_required
def toggle_cooking_meal():
    agent = get_agent()
    data = request.json
    meal_id = data.get('meal_id') # format: date-mealtype
    
    active_path = os.path.join(agent.user_state_dir, 'active_plan.json')
    if not os.path.exists(active_path):
        return jsonify({"status": "error", "message": "No active plan"}), 404
        
    try:
        with open(active_path, 'r') as f:
            plan = json.load(f)
            
        if 'completed_meals' not in plan:
            plan['completed_meals'] = {}
            
        current_state = plan['completed_meals'].get(meal_id, False)
        new_state = not current_state
        plan['completed_meals'][meal_id] = new_state
            
        with open(active_path, 'w') as f:
            json.dump(plan, f, indent=4)
            
        return jsonify({"status": "ok", "completed": new_state})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/plan/grocery/pantry_check', methods=['POST'])
@login_required
def run_pantry_check():
    agent = get_agent()
    active_path = os.path.join(agent.user_state_dir, 'active_plan.json')
    if not os.path.exists(active_path):
        return jsonify({"status": "error", "message": "No active plan"}), 404
        
    try:
        with open(active_path, 'r') as f:
            plan = json.load(f)
            
        new_checks = agent.recommend_grocery_checks(plan)
        
        # Merge with existing
        if 'pantry_recommendations' not in plan:
            plan['pantry_recommendations'] = []
            
        # Add new ones if unique
        for item_id in new_checks:
            if item_id not in plan['pantry_recommendations']:
                plan['pantry_recommendations'].append(item_id)
                
        with open(active_path, 'w') as f:
            json.dump(plan, f, indent=4)
            
        return jsonify({"status": "ok", "recommended_checks": plan['pantry_recommendations']})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/plan/grocery/add_to_pantry', methods=['POST'])
@login_required
def add_grocery_to_pantry():
    agent = get_agent()
    active_path = os.path.join(agent.user_state_dir, 'active_plan.json')
    if not os.path.exists(active_path):
        return jsonify({"status": "error", "message": "No active plan"}), 404
        
    try:
        with open(active_path, 'r') as f:
            plan = json.load(f)
            
        checked_groceries = plan.get('checked_groceries', {})
        pantry_recommendations = plan.get('pantry_recommendations', [])
        
        # Find ingredient strings for items that are checked 
        # but NOT already recommended (already in pantry)
        items_to_add = []
        handled_ids = []
        
        for day in plan.get('days', []):
            for meal_type in ['breakfast', 'lunch', 'dinner']:
                meal = day.get(meal_type)
                if not meal: continue
                # Use enumerate to match the item_id logic in grocery_list.html
                for i, ing in enumerate(meal.get('ingredients', [])):
                    item_id = f"{day['date']}-{meal_type}-{i}"
                    if checked_groceries.get(item_id) and item_id not in pantry_recommendations:
                        items_to_add.append(ing)
                        handled_ids.append(item_id)
        
        if not items_to_add:
            return jsonify({"status": "ok", "count": 0, "message": "No new items to add."})
            
        # Parse and add to inventory using InventoryManager
        raw_text = "\n".join(items_to_add)
        count = agent.inventory_manager.parse_and_add(raw_text)
        
        # Mark these items as "in pantry" so they get the green badge on refresh
        if 'pantry_recommendations' not in plan:
            plan['pantry_recommendations'] = []
            
        for h_id in handled_ids:
            if h_id not in plan['pantry_recommendations']:
                plan['pantry_recommendations'].append(h_id)
        
        with open(active_path, 'w') as f:
            json.dump(plan, f, indent=4)
            
        return jsonify({"status": "ok", "count": count})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/plan/grocery/add_one_to_pantry', methods=['POST'])
@login_required
def add_one_grocery_to_pantry():
    agent = get_agent()
    data = request.json
    ingredient_str = data.get('ingredient')
    item_id = data.get('item_id')
    
    if not ingredient_str:
        return jsonify({"status": "error", "message": "Missing ingredient"}), 400

    active_path = os.path.join(agent.user_state_dir, 'active_plan.json')
    
    try:
        success, message = agent.inventory_manager.add_one_smartly(ingredient_str)
        
        if success and item_id:
             # Mark as "in pantry" so it gets the green badge
             if os.path.exists(active_path):
                 with open(active_path, 'r') as f:
                     plan = json.load(f)
                 
                 if 'pantry_recommendations' not in plan:
                     plan['pantry_recommendations'] = []
                 
                 if item_id not in plan['pantry_recommendations']:
                     plan['pantry_recommendations'].append(item_id)
                 
                 with open(active_path, 'w') as f:
                     json.dump(plan, f, indent=4)

        return jsonify({"status": "ok" if success else "error", "message": message})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/pantry/remove_by_recipe_item', methods=['POST'])
@login_required
def remove_ingredient_from_cooking():
    agent = get_agent()
    data = request.json
    ingredient_str = data.get('ingredient')
    if not ingredient_str:
        return jsonify({"status": "error", "message": "Missing ingredient string"}), 400
        
    try:
        success, message = agent.inventory_manager.remove_by_recipe_item(ingredient_str)
        if success:
            return jsonify({"status": "ok", "message": message})
        else:
            return jsonify({"status": "not_found", "message": message})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/ideas')
@login_required
def ideas_page():
    return render_template('ideas.html', user=current_user)

@app.route('/library')
@login_required
def library_page():
    agent = get_agent()
    from app.core.cookbook_manager import CATEGORIES, PROTEINS
    recipes = agent.cookbook_manager.load_recipes()
    
    # Filter/Search logic
    query = request.args.get('q')
    category_filter = request.args.get('category')
    protein_filter = request.args.get('protein')

    if query:
        query = query.lower()
        recipes = [r for r in recipes if query in r['name'].lower() or query in str(r.get('ingredients')).lower()]
    
    if category_filter:
        recipes = [r for r in recipes if r.get('category') == category_filter]

    if protein_filter:
        recipes = [r for r in recipes if r.get('protein') == protein_filter]
        
    return render_template('cookbook.html', recipes=recipes, categories=CATEGORIES, proteins=PROTEINS, user=current_user)

# --- SYNC STATUS (Multi-User) ---
# Dict: user_id -> sync_status_dict
USER_SYNC_STATS = {}

def get_user_sync_status(user_id):
    if user_id not in USER_SYNC_STATS:
        USER_SYNC_STATS[user_id] = {
            "is_syncing": False,
            "current": 0,
            "total": 0,
            "message": "Idle",
            "percent": 0,
            "cancel_requested": False
        }
    return USER_SYNC_STATS[user_id]

def run_sync_job(user_id):
    status = get_user_sync_status(user_id)
    status["is_syncing"] = True
    status["cancel_requested"] = False
    status["message"] = "Starting sync..."
    
    # We need a fresh agent for the thread
    from app.core.agent import ArbyAgent
    thread_agent = ArbyAgent(base_dir, user_id=user_id)
    
    def callback(curr, total, msg):
        status["current"] = curr
        status["total"] = total
        status["message"] = msg
        if total > 0:
            status["percent"] = int((curr / total) * 100)
        else:
            status["percent"] = 0

    def check_cancel():
        return status.get("cancel_requested", False)

    try:
        librarian_id = thread_agent.model_manager.get_librarian_model_id()
        added_recipes = thread_agent.cookbook_manager.sync_library(progress_callback=callback, model_id=librarian_id, cancel_check=check_cancel)
        
        if status.get("cancel_requested"):
             status["message"] = "Sync Stopped."
        else:
             if added_recipes:
                  names_str = ", ".join(added_recipes)
                  if len(names_str) > 50:
                      names_str = names_str[:47] + "..."
                  status["message"] = f"Sync Complete! Added: {names_str}"
             else:
                  status["message"] = "Sync Complete! No new recipes found."
             status["percent"] = 100
             
    except Exception as e:
        status["message"] = f"Error: {e}"
        import traceback
        traceback.print_exc()
    finally:
        time.sleep(1) # Let UI see message
        status["is_syncing"] = False
        status["cancel_requested"] = False

@app.route('/library/sync', methods=['POST'])
@login_required
def sync_cookbook():
    status = get_user_sync_status(current_user.id)
    if status["is_syncing"]:
        return jsonify({"status": "already_running"}), 200
        
    threading.Thread(target=run_sync_job, args=(current_user.id,)).start()
    return jsonify({"status": "started"}), 200

@app.route('/library/sync/cancel', methods=['POST'])
@login_required
def cancel_sync():
    status = get_user_sync_status(current_user.id)
    if status["is_syncing"]:
        status["cancel_requested"] = True
        return jsonify({"status": "cancel_requested"}), 200
    return jsonify({"status": "not_running"}), 200

@app.route('/library/sync/status')
@login_required
def sync_status():
    return jsonify(get_user_sync_status(current_user.id))


from flask import send_from_directory

@app.route('/library/pdf/<path:filename>')
@login_required
def serve_recipe_pdf(filename):
    agent = get_agent()
    return send_from_directory(agent.cookbook_manager.library_path, filename)

@app.route('/library/add', methods=['GET', 'POST'])
@login_required
def add_recipe():
    agent = get_agent()
    from app.core.cookbook_manager import CATEGORIES, PROTEINS
    if request.method == 'POST':
        recipe_data = {
            "name": request.form.get('name'),
            "category": request.form.get('category'),
            "protein": request.form.get('protein'),
            "ingredients": request.form.get('ingredients').split('\n'),
            "instructions": request.form.get('instructions').split('\n'),
            "source": request.form.get('source', 'user')
        }
        agent.cookbook_manager.add_recipe(recipe_data)
        flash("Recipe added!", "success")
        return redirect('/library')
    return render_template('recipe_form.html', categories=CATEGORIES, proteins=PROTEINS, user=current_user)

@app.route('/library/edit/<recipe_id>', methods=['GET', 'POST'])
@login_required
def edit_recipe(recipe_id):
    agent = get_agent()
    from app.core.cookbook_manager import CATEGORIES, PROTEINS
    
    if not recipe_id:
        return redirect('/library')

    if request.method == 'POST':
        updates = {
            "name": request.form.get('name'),
            "category": request.form.get('category'),
            "protein": request.form.get('protein'),
            "ingredients": request.form.get('ingredients').split('\n'),
            "instructions": request.form.get('instructions').split('\n'),
            "source": request.form.get('source')
        }
        agent.cookbook_manager.update_recipe(recipe_id, updates)
        flash("Recipe updated!", "success")
        return redirect('/library')
    
    recipe = agent.cookbook_manager.get_recipe(recipe_id)
    if not recipe:
        flash("Recipe not found", "error")
        return redirect('/library')
    return render_template('recipe_form.html', recipe=recipe, categories=CATEGORIES, proteins=PROTEINS, user=current_user)

@app.route('/library/delete/<recipe_id>', methods=['POST'])
@login_required
def delete_recipe(recipe_id):
    agent = get_agent()
    if agent.cookbook_manager.delete_recipe(recipe_id):
        flash("Recipe deleted.", "success")
    else:
        flash("Error deleting recipe.", "error")
    return redirect('/library')

@app.route('/library/ignored')
@login_required
def view_ignored_files():
    agent = get_agent()
    blacklist = agent.cookbook_manager.load_blacklist()
    return render_template('ignored_files.html', blacklist=blacklist, user=current_user)

@app.route('/library/restore/<path:filename>', methods=['POST'])
@login_required
def restore_file(filename):
    agent = get_agent()
    if agent.cookbook_manager.restore_ignored_file(filename):
        flash(f"Restored '{filename}'. It will be re-imported on next sync.", "success")
    else:
        flash("Error restoring file.", "error")
    return redirect('/library/ignored')

@app.route('/library/view/<recipe_id>')
@login_required
def view_recipe(recipe_id):
    agent = get_agent()
    recipe = agent.cookbook_manager.get_recipe(recipe_id)
    if not recipe:
        flash("Recipe not found", "error")
        return redirect('/library')
    return render_template('recipe_detail.html', recipe=recipe, user=current_user)

@app.route('/api/library/add_from_plan', methods=['POST'])
@login_required
def save_from_plan_api():
    """API endpoint to save a recipe from a plan to the cookbook."""
    agent = get_agent()
    data = request.json
    if not data or not data.get('name'):
        return jsonify({"status": "error", "message": "Missing recipe data"}), 400
    
    try:
        recipe_data = {
            "name": data.get('name'),
            "ingredients": data.get('ingredients', []),
            "instructions": data.get('instructions', []),
            "category": data.get('category', 'Main'),
            "protein": data.get('protein', 'Vegetarian'),
            "source": "chef"
        }
        recipe = agent.cookbook_manager.add_recipe(recipe_data)
        return jsonify({"status": "ok", "message": f"Saved {recipe.name} to cookbook!", "id": recipe.id})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/library/rate', methods=['POST'])
@login_required
def rate_recipe_endpoint():
    agent = get_agent()
    data = request.json
    if not data or not data.get('id') or data.get('rating') is None:
        return jsonify({"status": "error", "message": "Missing id or rating"}), 400
        
    try:
        rating = int(data.get('rating'))
        if rating < 0 or rating > 5:
             return jsonify({"status": "error", "message": "Rating must be 0-5"}), 400
             
        if agent.cookbook_manager.rate_recipe(data.get('id'), rating):
            return jsonify({"status": "ok", "message": "Rated!"})
        else:
             return jsonify({"status": "error", "message": "Recipe not found"}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/library/save_from_plan', methods=['POST'])
@login_required
def save_from_plan_form():
    """Form-based version of saving from plan (redirects back)."""
    agent = get_agent()
    name = request.form.get('name')
    if not name:
        flash("Missing recipe name", "error")
        return redirect(request.referrer or '/')
        
    try:
        # We expect ingredients and instructions to be newline-separated strings
        ingredients = [i.strip() for i in request.form.get('ingredients', '').split('\n') if i.strip()]
        instructions = [i.strip() for i in request.form.get('instructions', '').split('\n') if i.strip()]
        
        recipe_data = {
            "name": name,
            "ingredients": ingredients,
            "instructions": instructions,
            "category": request.form.get('category', 'Main'),
            "protein": request.form.get('protein', 'Vegetarian'),
            "source": "chef"
        }
        agent.cookbook_manager.add_recipe(recipe_data)
        flash(f"Saved {name} to your Cookbook!", "success")
    except Exception as e:
        flash(f"Error saving recipe: {str(e)}", "error")
        
    return redirect(request.referrer or '/cookbook')

@app.route('/api/plan/active/rate_meal', methods=['POST'])
@login_required
def rate_active_meal():
    agent = get_agent()
    data = request.json
    date_str = data.get('date')
    meal_type = data.get('meal_type')
    rating = int(data.get('rating', 0))
    
    active_path = os.path.join(agent.user_state_dir, 'active_plan.json')
    if not os.path.exists(active_path):
        return jsonify({"status": "error", "message": "No active plan"}), 404
        
    try:
        with open(active_path, 'r') as f:
            plan = json.load(f)
            
        # Update in plan
        for day in plan.get('days', []):
            if day['date'] == date_str:
                meal = day.get(meal_type)
                if meal:
                    meal['rating'] = rating
                    # If it's a library recipe, ALSO update the library!
                    recipes = agent.cookbook_manager.load_recipes()
                    match = next((r for r in recipes if r['name'].lower() == meal['name'].lower()), None)
                    if match:
                        agent.cookbook_manager.rate_recipe(match['id'], rating)
        
        with open(active_path, 'w') as f:
            json.dump(plan, f, indent=4)
            
        return jsonify({"status": "ok"})
    except Exception as e:
         return jsonify({"status": "error", "message": str(e)}), 500

from app.core.cookbook_manager import CookbookManager
# Removed global manager logic

# ... routes ...

import calendar

@app.route('/api/estimate', methods=['POST'])
@login_required
def estimate_cost_endpoint():
    agent = get_agent()
    try:
        model_id = request.json.get('model_id')
        if not model_id: return jsonify({"error": "No model_id"}), 400
        
        # Get optional dynamic params
        start_date = request.json.get('start_date')
        duration = request.json.get('duration') # might be string or int
        
        # 1. Construct Prompt (Dry Run)
        # Pass start_date and duration to get the actual prompt size that would be sent
        sys_p, user_p = agent.construct_prompt(start_date=start_date, duration=duration)
        full_text = sys_p + "\n" + user_p
        
        # 2. Count Tokens (Approx)
        char_count = len(full_text)
        est_input_tokens = char_count / 4
        
        # If PDFs exist, add a buffer? 
        # Checking PDF folder
        if os.path.exists(agent.pdf_folder):
             # Hard to guess valid token count of PDFs without reading them.
             # Let's add a fixed buffer if PDFs are present
             num_pdfs = len([f for f in os.listdir(agent.pdf_folder) if f.endswith('.pdf')])
             if num_pdfs > 0:
                 est_input_tokens += (num_pdfs * 5000) # Assuming 5k tokens per PDF? Conservative.
                 
        # Dynamic Output Tokens
        # Base overhead + (tokens per meal * num_meals)
        # 1. Determine Start Date
        if start_date:
            if isinstance(start_date, str):
                 start_date_obj = datetime.strptime(start_date, "%Y-%m-%d")
        else:
             today = datetime.now()
             start_date_obj = today + timedelta(days=1)
             
        # 2. Determine Duration
        try:
            days_to_plan = int(duration) if duration else 4
        except:
            days_to_plan = 4
            
        # 3. Count Active Slots
        config = agent.calendar_manager.load_config()
        total_meal_slots = 0
        
        for i in range(days_to_plan):
            d = start_date_obj + timedelta(days=i)
            day_name = d.strftime("%A")
            day_sched = config['schedule'].get(day_name, {})
            # day_sched is {"breakfast": True, "lunch": False, ...}
            total_meal_slots += sum(1 for active in day_sched.values() if active)
            
        # Assuming ~500 output tokens per meal recipe + 500 overhead
        est_output_tokens = 500 + (total_meal_slots * 500)
        
        # 3. Calculate Cost
        all_models = agent.model_manager.get_available_models()
        model_conf = next((m for m in all_models if m['id'] == model_id), {})
        
        cost_in_rate = model_conf.get('cost_in', 0.0)
        cost_out_rate = model_conf.get('cost_out', 0.0)
        
        cost = (est_input_tokens / 1_000_000 * cost_in_rate) + (est_output_tokens / 1_000_000 * cost_out_rate)
        
        return jsonify({
            "estimated_cost": cost,
            "currency": "$",
            "details": f"{int(est_input_tokens)} in / {est_output_tokens} out"
        })
    except Exception as e:
         return jsonify({"error": str(e)}), 500

@app.route('/api/test_model', methods=['POST'])
@login_required
def test_model_endpoint():
    agent = get_agent()
    try:
        model_id = request.json.get('model_id')
        status, msg = agent.model_manager.test_connection(model_id)
        return jsonify({"status": status, "msg": msg})
    except Exception as e:
        print(f"DEBUG: Error in test_model_endpoint: {e}")
        return jsonify({"status": "error", "msg": str(e)}), 500

@app.route('/api/test_all', methods=['POST'])
@login_required
def test_all_models_endpoint():
    agent = get_agent()
    try:
        # Get list of all unlocked models
        models = agent.model_manager.get_available_models()
        unlocked_models = [m['id'] for m in models if not m.get('locked')]
        
        results = []
        for mid in unlocked_models:
             status, msg = agent.model_manager.test_connection(mid)
             results.append({"id": mid, "status": status, "msg": msg})
             
        return jsonify({"status": "ok", "results": results})
    except Exception as e:
        print(f"DEBUG: Error in test_all_models_endpoint: {e}")
        return jsonify({"status": "error", "msg": str(e)}), 500

@app.route('/settings/core_model', methods=['POST'])
@login_required
def update_core_model():
    agent = get_agent()
    model_id = request.form.get('core_model_id')
    if model_id:
        agent.model_manager.set_core_model(model_id)
        flash(f"Head Chef updated to {model_id}.", "success")
    return redirect('/settings')

@app.route('/settings/sous_chef_model', methods=['POST'])
@login_required
def update_sous_chef_model():
    agent = get_agent()
    model_id = request.form.get('sous_chef_model_id')
    if model_id:
        agent.model_manager.set_sous_chef_model(model_id)
        flash(f"Sous Chef updated to {model_id}.", "success")
    return redirect('/settings')

@app.route('/settings/librarian_model', methods=['POST'])
@login_required
def update_librarian_model():
    agent = get_agent()
    model_id = request.form.get('librarian_model_id')
    if model_id:
        agent.model_manager.set_librarian_model(model_id)
        flash(f"Librarian updated to {model_id}.", "success")
    return redirect('/settings')

@app.route('/calendar/widget')
@login_required
def calendar_widget():
    """
    Returns a partial HTML for the calendar widget.
    Accepts 'date' (default: today), 'duration' (default: 4 or from config), and 'view' (default: custom range).
    """
    agent = get_agent()
    ref_date_str = request.args.get('date')
    duration_str = request.args.get('duration')
    
    if ref_date_str:
        try:
            ref_date = datetime.strptime(ref_date_str, '%Y-%m-%d').date()
        except:
            ref_date = date.today()
    else:
        ref_date = date.today()

    # Determine duration
    cal_manager = agent.calendar_manager
    config = cal_manager.load_config()
    
    if duration_str:
        try:
            duration = min(int(duration_str), 7)
        except:
            duration = config.get('duration_days', 4)
    else:
        duration = min(config.get('duration_days', 4), 7)

    events = cal_manager.load_calendar()
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    
    # Calculate visual plan window
    plan_window_dates = [ (ref_date + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(duration) ]
    
    calendar_days = []
    today = date.today()
    
    for i in range(duration):
        date_obj = ref_date + timedelta(days=i)
        date_str = date_obj.strftime("%Y-%m-%d")
        day_name = date_obj.strftime("%A")
        
        content = events.get(date_str, {})
        
        day_data = {
            "date_obj": date_obj,
            "date_iso": date_str,
            "date_num": date_obj.day,
            "date_str": date_str,
            "day_name": day_name,
            "is_today": (date_obj == today),
            "in_month": True, 
            "in_plan_window": True, 
            "content": content
        }
        calendar_days.append(day_data)

    return render_template(
        'calendar_partial.html',
        calendar_days=calendar_days,
        view_mode='custom',
        ref_date=ref_date,
        config=config,
        user=current_user
    )

@app.route('/settings/models/cost', methods=['POST'])
@login_required
def update_model_cost():
    agent = get_agent()
    model_id = request.form.get('model_id')
    cost_in = request.form.get('cost_in')
    cost_out = request.form.get('cost_out')
    
    if model_id:
        agent.model_manager.update_model_cost(model_id, cost_in, cost_out)
        flash("Cost rates updated.", "success")
    return redirect('/settings')

@app.route('/calendar')
@login_required
def calendar_page():
    agent = get_agent()
    config = agent.calendar_manager.load_config()
    
    # Current Reference Date
    today = datetime.now()
    ref_date_str = request.args.get('date')
    if ref_date_str:
        try:
            ref_date = datetime.strptime(ref_date_str, "%Y-%m-%d")
        except:
            ref_date = today
    else:
        ref_date = today

    year = ref_date.year
    month = ref_date.month
    
    # --- VIEW MODE LOGIC ---
    view_mode = request.args.get('view', 'work_week')

    # Get Next Run for Planning Window
    next_run = agent.calendar_manager.get_next_run_dt()
    
    # Get Data from Manager
    calendar_days = agent.calendar_manager.get_days_for_view(ref_date, view_mode, next_run_dt=next_run)
    
    # Navigation Deltas
    if view_mode == 'month':
        next_date = ref_date + timedelta(days=30)
        prev_date = ref_date - timedelta(days=30)
            
    elif view_mode == 'week':
        next_date = ref_date + timedelta(days=7)
        prev_date = ref_date - timedelta(days=7)

    elif view_mode == 'work_week':
        next_date = ref_date + timedelta(days=5)
        prev_date = ref_date - timedelta(days=5)
        
    elif view_mode == '3day':
        next_date = ref_date + timedelta(days=3)
        prev_date = ref_date - timedelta(days=3)
        
    elif view_mode == 'day':
        next_date = ref_date + timedelta(days=1)
        prev_date = ref_date - timedelta(days=1)
        
    else:
        next_date = ref_date + timedelta(days=30)
        prev_date = ref_date - timedelta(days=30)
        
    # Formatting for Display
    month_name = ref_date.strftime("%B")
    
    # Default Start Date for Generating
    default_start = agent.calendar_manager.get_default_start_date()
    if default_start < date.today():
        default_start = date.today()
    default_start_iso = default_start.strftime("%Y-%m-%d")

    # Identifiers for next 14 days
    days_data = []
    base = datetime.now()
    for i in range(14):
        d = base + timedelta(days=i)
        days_data.append({
            "day": d.strftime("%Y-%m-%d"),
            "label": f"{d.strftime('%A')} ({d.strftime('%b %d')})"
        })

    # Get Models for Selector
    available_models = agent.model_manager.get_available_models()
    current_model = next((m for m in available_models if m.get('is_core')), None)
    if not current_model:
         current_model = next((m for m in available_models if not m.get('locked')), None)

    # Load Prefs for modal
    pref_path = agent.pref_file
    prefs = {}
    if os.path.exists(pref_path):
        with open(pref_path, 'r') as f:
            prefs = json.load(f)

    # Defaults to prevent Jinja errors
    if 'data_context' not in prefs:
        prefs['data_context'] = {
            "use_inventory": True,
            "use_history": True,
            "use_ideas": True,
            "use_cookbook": True
        }

    # Recipe Ideas for modal
    current_ideas = ""
    if os.path.exists(agent.ideas_file):
        with open(agent.ideas_file, 'r') as f:
            current_ideas = f.read().strip()

    return render_template('calendar.html', 
                           month_name=month_name,
                           month=month, 
                           year=year, 
                           ref_date=ref_date.strftime("%Y-%m-%d"),
                           next_date=next_date.strftime("%Y-%m-%d"),
                           prev_date=prev_date.strftime("%Y-%m-%d"),
                           today_date=today.strftime("%Y-%m-%d"),
                           calendar_days=calendar_days,
                           config=config,
                           schedule_enabled=config.get('schedule_enabled', True),
                           view_mode=view_mode,
                           default_start_date=default_start_iso,
                           run_day=config.get('run_day', 'Sunday'),
                           run_time=config.get('run_time', '10:00'),
                           duration_days=config.get('duration_days', 8),
                           next_run=format_date_suffix(next_run) if config.get('schedule_enabled', True) and next_run else "OFF",
                           days_data=days_data,
                           models=available_models,
                           current_model=current_model,
                           today_iso=today.strftime("%Y-%m-%d"),
                           prefs=prefs,
                           current_ideas=current_ideas,
                           user=current_user)

@app.route('/calendar/settings', methods=['POST'])
@login_required
def update_settings():
    agent = get_agent()
    try:
        # Load existing config to merge
        config = agent.calendar_manager.load_config()
        
        new_schedule = {}
        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        meals = ["breakfast", "lunch", "dinner"]
        
        for day in days:
            new_schedule[day] = {}
            for meal in meals:
                key = f"{day}_{meal}"
                new_schedule[day][meal] = (key in request.form)
                
        config["duration_days"] = int(request.form.get('duration_days', config.get('duration_days', 8)))
        config["schedule"] = new_schedule
        config["view_mode"] = request.form.get('view_mode', config.get('view_mode', 'month'))
        
        agent.calendar_manager.save_config(config)
        flash("Schedule settings saved!", "success")
    except Exception as e:
        flash(f"Error saving settings: {e}", "error")
    
    # Redirect keeping the view mode
    return redirect(url_for('calendar_page', view=request.form.get('view_mode', 'month')))


@app.route('/calendar/set_duration', methods=['POST'])
@login_required
def set_duration():
    agent = get_agent()
    try:
        duration = int(request.form.get('duration_days', 7))
        view_mode = request.form.get('view_mode', 'month')
        date_str = request.form.get('date') # Preserve focus date
        
        config = agent.calendar_manager.load_config()
        config['duration_days'] = duration
        agent.calendar_manager.save_config(config)
        
        flash(f"Planning horizon set to {duration} days", "success")
        return redirect(url_for('calendar_page', view=view_mode, date=date_str))
    except Exception as e:
        flash(f"Error saving duration: {e}", "error")
        return redirect(url_for('calendar_page'))

@app.route('/calendar/toggle_slot', methods=['POST'])
@login_required
def toggle_slot():
    agent = get_agent()
    day = request.form.get('day')
    meal = request.form.get('meal')
    view_mode = request.form.get('view_mode', 'month')
    date_str = request.form.get('date') # Specific date (e.g. 2024-03-20)
    
    if not day or not meal:
        return "Missing arguments", 400
        
    try:
        config = agent.calendar_manager.load_config()
        # Toggle boolean in config
        if day in config['schedule'] and meal in config['schedule'][day]:
            new_state = not config['schedule'][day][meal]
            config['schedule'][day][meal] = new_state
            agent.calendar_manager.save_config(config)
            
        return redirect(url_for('calendar_page', view=view_mode, date=date_str))
    except Exception as e:
        flash(f"Error toggling slot: {e}", "error")
        return redirect(url_for('calendar_page', view=view_mode))


@app.route('/api/schedule/settings', methods=['POST'])
@login_required
def api_update_schedule_settings():
    agent = get_agent()
    try:
        data = request.json
        run_day = data.get('run_day')
        run_time = data.get('run_time')
        
        if not run_day or not run_time:
            return jsonify({"status": "error", "message": "Missing run_day or run_time"}), 400
            
        config = agent.calendar_manager.load_config()
        config['run_day'] = run_day
        config['run_time'] = run_time
        if data.get('duration'):
            config['duration_days'] = int(data.get('duration'))
        agent.calendar_manager.save_config(config)
        
        # Re-init scheduler with new settings
        init_scheduler()
        
        # Get new next run time
        next_run = agent.calendar_manager.get_next_run_dt()
        next_run_str = format_date_suffix(next_run)
        
        return jsonify({
            "status": "ok", 
            "next_run": next_run_str,
            "run_day": run_day,
            "run_time": run_time
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/schedule/toggle', methods=['POST'])
@login_required
def api_toggle_schedule():
    agent = get_agent()
    try:
        config = agent.calendar_manager.load_config()
        new_state = not config.get('schedule_enabled', True)
        config['schedule_enabled'] = new_state
        agent.calendar_manager.save_config(config)
        return jsonify({"status": "ok", "new_state": new_state})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/calendar/toggle', methods=['POST'])
@login_required
def api_toggle_slot():
    """
    AJAX endpoint to toggle a meal slot on/off.
    json body: { "day": "Monday", "meal": "breakfast", "date": "optional YYYY-MM-DD" }
    """
    agent = get_agent()
    data = request.json
    day_name = data.get('day')
    meal_type = data.get('meal')
    date_str = data.get('date')
    
    if not day_name or not meal_type:
        return jsonify({"error": "Missing day or meal"}), 400
        
    config = agent.calendar_manager.load_config()
    schedule = config.get('schedule', {})
    
    if day_name in schedule:
        current_val = schedule[day_name].get(meal_type, True)
        new_state = not current_val
        schedule[day_name][meal_type] = new_state
        agent.calendar_manager.save_config(config)
            
        return jsonify({"status": "ok", "new_state": new_state})
    
    return jsonify({"error": "Invalid day"}), 400

@app.route('/api/ideas', methods=['GET', 'POST'])
@login_required
def handle_ideas():
    agent = get_agent()
    ideas_path = agent.ideas_file
    if request.method == 'POST':
        data = request.json
        ideas = data.get('ideas', '')
        with open(ideas_path, 'w') as f:
            f.write(ideas)
        return jsonify({"status": "ok"})
    
    # GET
    ideas = ""
    if os.path.exists(ideas_path):
        with open(ideas_path, 'r') as f:
            ideas = f.read()
    return jsonify({"ideas": ideas})

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5005, debug=True)
