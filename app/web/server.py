import os
import json
import sys
from datetime import datetime, timedelta, date, time as dt_time
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from dotenv import load_dotenv
import re
import threading
import schedule
import schedule
import time
import subprocess

# ... imports ...

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
        
    return dict(app_version="v1.0.1", git_hash=git_hash)
# CAPTURE ORIGINAL SYSTEM ENVIRONMENT before load_dotenv shadows it
original_env = os.environ.copy()

# Ensure app modules are found
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from app.core.agent import ArbyAgent
from app.core.inventory_manager import InventoryManager
from app.core.review_manager import ReviewManager

load_dotenv()

app = Flask(__name__)
# Secret key needed for flash messages
app.secret_key = os.environ.get("FLASK_SECRET", "dev-secret-key-change-me")

base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../'))
agent = ArbyAgent(base_dir, original_env=original_env)
inventory_manager = InventoryManager(os.path.join(base_dir, 'state/inventory.json'), model_manager=agent.model_manager)
review_manager = ReviewManager(base_dir, model_manager=agent.model_manager)

# --- SCHEDULER ---
def run_agent_job():
    config = agent.calendar_manager.load_config()
    if not config.get('schedule_enabled', True):
        print("Scheduled Job skipped (Disabled in settings).")
        return
        
    print("Running Scheduled Job...")
    agent.run()

def schedule_runner():
    while True:
        schedule.run_pending()
        time.sleep(60)

def init_scheduler():
    """Initializes or re-initializes the schedule based on config."""
    schedule.clear()
    config = agent.calendar_manager.load_config()
    run_day = config.get('run_day', 'Sunday').lower()
    run_time = config.get('run_time', '10:00')
    
    # Map day names to schedule methods
    day_map = {
        "monday": schedule.every().monday,
        "tuesday": schedule.every().tuesday,
        "wednesday": schedule.every().wednesday,
        "thursday": schedule.every().thursday,
        "friday": schedule.every().friday,
        "saturday": schedule.every().saturday,
        "sunday": schedule.every().sunday
    }
    
    job_builder = day_map.get(run_day, schedule.every().sunday)
    job_builder.at(run_time).do(run_agent_job)
    print(f"Scheduler initialized: Every {run_day.capitalize()} at {run_time}")

init_scheduler()
threading.Thread(target=schedule_runner, daemon=True).start()

# Helper for display
def format_date_suffix(dt):
    if not dt: return "Not Scheduled"
    suffix = "th" if 11 <= dt.day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(dt.day % 10, "th")
    # %p returns AM/PM, using abbreviated month for space
    return dt.strftime(f"%A, %b {dt.day}{suffix} at %I:%M %p").replace("AM", "am").replace("PM", "pm")

# --- ROUTES ---
@app.route('/')
def index():
    # Load Config
    config = agent.calendar_manager.load_config()
    schedule_enabled = config.get('schedule_enabled', True)

    # Pass necessary data to dashboard
    next_run_dt = agent.calendar_manager.get_next_run_dt()
    if schedule_enabled and next_run_dt:
        next_run_str = format_date_suffix(next_run_dt)
    else:
        next_run_str = "None"
    
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
    
    current_ideas = ""
    if os.path.exists(os.path.join(base_dir, 'state/ideas.txt')):
        with open(os.path.join(base_dir, 'state/ideas.txt'), 'r') as f:
            current_ideas = f.read().strip()
    
    # Get Models for Selector
    available_models = agent.model_manager.get_available_models()
    
    # Identify Current Head Chef
    current_model = next((m for m in available_models if m.get('is_core')), None)
            
    # Fallback if no core model set (shouldn't happen if default exists)
    if not current_model:
         current_model = next((m for m in available_models if not m.get('locked')), None)

    # Identifiers for next 14 days (for settings select labels)
    days_data = []
    base = datetime.now()
    for i in range(14):
        d = base + timedelta(days=i)
        days_data.append({
            "day": d.strftime("%A"),
            "label": f"{d.strftime('%A')} ({d.strftime('%b %d')})"
        })

    # Default Start Date Logic
    # We still calculate this for the generate modal even if auto-schedule is off
    next_run_ref = next_run_dt
    if not next_run_ref:
        next_run_ref = datetime.now()
        
    next_run_str = format_date_suffix(next_run_ref) if config.get('schedule_enabled', True) else "Not Scheduled"
    
    default_start = agent.calendar_manager.get_default_start_date(next_run_ref)
    default_start_iso = default_start.strftime("%Y-%m-%d")
    default_start_pretty = default_start.strftime("%a, %b %d")

    # Check for active plan
    active_plan_exists = os.path.exists(os.path.join(agent.state_dir, 'active_plan.json'))

    return render_template('index.html', 
                           next_run=next_run_str, 
                           last_run=last_run, 
                           current_ideas=current_ideas, 
                           models=available_models, 
                           current_model=current_model,
                           default_start_date=default_start_iso,
                           schedule_enabled=schedule_enabled,
                           active_plan_exists=active_plan_exists,
                           run_day=config.get('run_day', 'Sunday'),
                           run_time=config.get('run_time', '10:00'),
                           duration_days=config.get('duration_days', 8),
                           days_data=days_data,
                           default_start_date_pretty=default_start_pretty)

@app.route('/health')
def health_check():
    """Simple health check for monitoring scripts."""
    return {"status": "healthy", "version": "1.0.0"}

@app.route('/settings', methods=['GET', 'POST'])
def settings_page():
    if request.method == 'POST':
        # Update .env file safely
        env_path = os.path.join(base_dir, '.env')
        keys_to_update = {
            "GEMINI_API_KEY": request.form.get("gemini_key"),
            "OPENAI_API_KEY": request.form.get("openai_key"),
            "ANTHROPIC_API_KEY": request.form.get("anthropic_key"),
            "XAI_API_KEY": request.form.get("xai_key"),
        }
        
        try:
            # Read existing
            with open(env_path, 'r') as f:
                lines = f.readlines()
            
            new_lines = []
            updated_keys = set()
            
            for line in lines:
                key_match = None
                for k, v in keys_to_update.items():
                    # Matches "KEY=", "KEY =", "KEY  =" etc.
                    if re.match(rf'^\s*{k}\s*=', line):
                        if v and v.strip() != "***": # Only update if provided and not masked
                             # Check if it's a known non-empty variable in ORIGINAL or CURRENT env
                             is_pointer = False
                             if (original_env and v in original_env and original_env[v]) or (os.environ.get(v)):
                                 is_pointer = True
                             
                             if is_pointer:
                                 v = f'${{{v}}}'
                             new_lines.append(f'{k}="{v}"\n')
                        else:
                             new_lines.append(line) # Keep existing
                        updated_keys.add(k)
                        key_match = True
                        break
                
                if not key_match:
                    new_lines.append(line)
            
            for k, v in keys_to_update.items():
                if k not in updated_keys and v and v.strip() != "***":
                    is_pointer = False
                    if (original_env and v in original_env and original_env[v]) or (os.environ.get(v)):
                         is_pointer = True
                    
                    if is_pointer:
                        v = f'${{{v}}}'
                    new_lines.append(f'{k}="{v}"\n')
            
            with open(env_path, 'w') as f:
                f.writelines(new_lines)
            
            # Reload Env
            load_dotenv(env_path, override=True)
            # Re-init Model Manager to pick up new keys
            agent.model_manager = agent.model_manager.__class__(base_dir=base_dir, original_env=original_env) 
            flash("Settings updated! Models unlocked based on new keys.", "success")
        except Exception as e:
            flash(f"Error saving settings: {e}", "error")
        return redirect('/settings')

    # GET
    # Fetch all models (including status) for management UI
    all_models = agent.model_manager.get_available_models()
    
    # Load Preferences
    pref_path = os.path.join(agent.state_dir, 'preferences.json')
    prefs = {}
    if os.path.exists(pref_path):
        with open(pref_path, 'r') as f:
            prefs = json.load(f)
    
    # Default data context if missing
    if 'data_context' not in prefs:
        prefs['data_context'] = {
            "use_inventory": True,
            "use_history": True,
            "use_ideas": True
        }

    # API Key Context for UI - Read RAW from .env to see pointers
    env_path = os.path.join(base_dir, '.env')
    raw_env = {}
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                if '=' in line and not line.startswith('#'):
                    k, v = line.split('=', 1)
                    raw_env[k.strip()] = v.strip().strip('"').strip("'")
    
    key_map = {
        "gemini": raw_env.get("GEMINI_API_KEY", ""),
        "openai": raw_env.get("OPENAI_API_KEY", ""),
        "anthropic": raw_env.get("ANTHROPIC_API_KEY", ""),
        "xai": raw_env.get("XAI_API_KEY", ""),
    }
    
    display_keys = {}
    for k, v in key_map.items():
        # A pointer is either "VAR" or "${VAR}"
        pure_var = v
        match = re.search(r'\$\{(.+?)\}', v)
        if match:
            pure_var = match.group(1)
        
        # Check if it's already in the process environment
        is_env_present = bool(os.environ.get(pure_var))
        # Or if it looks like a pointer (all caps/underscores, etc.)
        is_pointer_style = pure_var and re.match(r'^[A-Z0-9_]+$', pure_var) and len(pure_var) < 64
        if is_pointer_style and pure_var.startswith("AI"):
             is_pointer_style = False # Likely a raw Gemini key
        
        is_pointer = is_env_present or is_pointer_style
        resolved = agent.model_manager._resolve_key(v)
        
        status_msg = ""
        if is_pointer and not resolved:
            status_msg = "Pointer not found in system env"
        
        display_keys[k] = {
            "val": pure_var if is_pointer else ("***" if v else ""),
            "active": bool(resolved),
            "status": status_msg
        }

    current_ideas = ""
    if os.path.exists(os.path.join(base_dir, 'state/ideas.txt')):
        with open(os.path.join(base_dir, 'state/ideas.txt'), 'r') as f:
            current_ideas = f.read().strip()

    return render_template('settings.html', 
        display_keys=display_keys,
        models=all_models,
        pdf_library_path=cookbook_manager.library_path,
        state_folder_path=os.path.join(base_dir, 'state'),
        env_file_path=os.path.join(base_dir, '.env'),
        prefs=prefs,
        current_ideas=current_ideas,
        active_tab=request.args.get('tab', 'models')
    )

@app.route('/help')
def help_page():
    return render_template('help.html')

@app.route('/settings/preferences', methods=['POST'])
def update_preferences():
    pref_path = os.path.join(agent.state_dir, 'preferences.json')
    prefs = {}
    if os.path.exists(pref_path):
        with open(pref_path, 'r') as f:
            prefs = json.load(f)
            
    # Update Data Context
    prefs['data_context'] = {
        "use_inventory": 'use_inventory' in request.form,
        "use_history": 'use_history' in request.form,
        "use_ideas": 'use_ideas' in request.form,
    }
    
    # Update History Depth
    prefs['history_depth'] = int(request.form.get('history_depth', 50))
    
    # Update Long-term Preferences
    prefs['long_term_preferences'] = request.form.get('long_term_preferences', '')
    
    with open(pref_path, 'w') as f:
        json.dump(prefs, f, indent=4)
        
    flash("Data preferences updated!", "success")
    return redirect('/settings?tab=data')

@app.route('/settings/models/add', methods=['POST'])
def add_custom_model():
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
def delete_model():
    model_id = request.form.get('model_id')
    if model_id:
        agent.model_manager.hide_model(model_id)
        flash("Model removed from list.", "info")
    return redirect('/settings')


@app.route('/settings/models/restore', methods=['POST'])
def restore_models():
    agent.model_manager.restore_defaults()
    flash("Restored all default models.", "success")
    return redirect('/settings')

@app.route('/inventory')
def inventory_page():
    items = inventory_manager.load_inventory()
    # Sort by expiry if possible or just as is
    return render_template('inventory.html', items=enumerate(items))

@app.route('/inventory/add', methods=['POST'])
def add_inventory():
    raw_text = request.form.get('ingredients')
    if raw_text:
        try:
            count = inventory_manager.parse_and_add(raw_text)
            if count > 0:
                flash(f"Successfully added {count} items!", "success")
            else:
                flash("Could not parse items. Please try again or check your API quota.", "error")
        except Exception as e:
            flash(f"Error: {e}", "error")
    return redirect(url_for('inventory_page'))

# ... (inventory edit/delete routes stay same)

@app.route('/inventory/edit/<int:index>', methods=['POST'])
def edit_inventory(index):
    # ... (same as before)
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
    if inventory_manager.update_item(index, data):
        flash("Item updated.", "success")
    else:
        flash("Failed to update item.", "error")
    return redirect(url_for('inventory_page'))

@app.route('/inventory/increment/<int:index>', methods=['POST'])
def increment_inventory(index):
    inventory = inventory_manager.load_inventory()
    if 0 <= index < len(inventory):
        inventory[index]['quantity'] += 1
        inventory[index]['updated_on'] = datetime.now().strftime("%Y-%m-%d")
        inventory_manager.save_inventory(inventory)
        return jsonify({"status": "ok", "new_quantity": inventory[index]['quantity']})
    return jsonify({"status": "error"}), 404

@app.route('/generate', methods=['POST'])
def generate_plan():
    """Generates a DRAFT plan and redirects to review page."""
    model_id = request.form.get('model_id')
    start_date = request.form.get('start_date')
    duration = request.form.get('duration')
    
    # Persist Preference
    if model_id:
        try:
            pref_path = os.path.join(base_dir, 'state/preferences.json')
            prefs = {}
            if os.path.exists(pref_path):
                with open(pref_path, 'r') as f:
                    prefs = json.load(f)
            
            prefs['preferred_model'] = model_id
            
            with open(pref_path, 'w') as f:
                json.dump(prefs, f)
        except Exception as e:
            print(f"Failed to save preference: {e}")

    try:
        draft = agent.generate_draft(model_id=model_id, start_date=start_date, duration=duration)
        if "error" in draft:
            flash(f"Error: {draft['error']}", "error")
            return redirect('/')
            
        # Save Draft to State
        draft_path = os.path.join(agent.state_dir, 'current_draft.json')
        with open(draft_path, 'w') as f:
            json.dump(draft, f, indent=4)
            
        return redirect('/plan/review')
    except Exception as e:
        print(f"Error generating: {e}")
        flash(f"Error generating plan: {str(e)}", "error")
        return redirect('/')

@app.route('/plan/review')
def review_plan_page():
    draft_path = os.path.join(agent.state_dir, 'current_draft.json')
    if not os.path.exists(draft_path):
        flash("No draft plan found. Please generate one first.", "warning")
        return redirect('/')
        
    with open(draft_path, 'r') as f:
        draft = json.load(f)
        
    return render_template('review_plan.html', plan=draft)

@app.route('/plan/modify', methods=['POST'])
def modify_plan():
    user_feedback = request.form.get('feedback')
    model_id = request.form.get('model_id') # Optional override
    
    draft_path = os.path.join(agent.state_dir, 'current_draft.json')
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
def modify_active_plan():
    user_feedback = request.form.get('feedback')
    
    active_path = os.path.join(agent.state_dir, 'active_plan.json')
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
def confirm_plan():
    draft_path = os.path.join(agent.state_dir, 'current_draft.json')
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
    active_path = os.path.join(agent.state_dir, 'active_plan.json')
    with open(active_path, 'w') as f:
        json.dump(draft, f, indent=4)
        
    # Remove Draft
    os.remove(draft_path)
    
    flash("Plan confirmed! Calendar updated and email sent.", "success")
    return redirect('/plan/view')

@app.route('/plan/view')
def view_active_plan():
    active_path = os.path.join(agent.state_dir, 'active_plan.json')
    if not os.path.exists(active_path):
         flash("No active detailed plan found.", "info")
         return redirect('/calendar')
         
    with open(active_path, 'r') as f:
        plan = json.load(f)
        
    # Enrich plan with current cookbook ratings
    recipes = cookbook_manager.load_recipes()
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
    
    return render_template('view_plan.html', plan=plan, title="Meal Plan")

@app.route('/plan/grocery')
def grocery_plan_page():
    active_path = os.path.join(agent.state_dir, 'active_plan.json')
    if not os.path.exists(active_path):
          flash("No active detailed plan found.", "info")
          return redirect('/calendar')
          
    with open(active_path, 'r') as f:
        plan = json.load(f)
        
    return render_template('grocery_list.html', plan=plan, title="Grocery List")

@app.route('/plan/cook')
def cook_plan_page():
    active_path = os.path.join(agent.state_dir, 'active_plan.json')
    if not os.path.exists(active_path):
          flash("No active detailed plan found.", "info")
          return redirect('/calendar')
          
    with open(active_path, 'r') as f:
        plan = json.load(f)
    
    return render_template('cooking_mode.html', plan=plan, title="Live Cooking")

@app.route('/api/plan/grocery/toggle_meal', methods=['POST'])
def toggle_grocery_meal_item():
    data = request.json
    item_id = data.get('item_id') # format: date-meal-index
    
    active_path = os.path.join(agent.state_dir, 'active_plan.json')
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
def toggle_cooking_ingredient():
    data = request.json
    item_id = data.get('item_id') # format: date-meal-index
    
    active_path = os.path.join(agent.state_dir, 'active_plan.json')
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
def toggle_cooking_step():
    data = request.json
    step_id = data.get('step_id') # format: date-meal-stepindex
    
    active_path = os.path.join(agent.state_dir, 'active_plan.json')
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
def toggle_cooking_meal():
    data = request.json
    meal_id = data.get('meal_id') # format: date-mealtype
    
    active_path = os.path.join(agent.state_dir, 'active_plan.json')
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
def run_pantry_check():
    active_path = os.path.join(agent.state_dir, 'active_plan.json')
    if not os.path.exists(active_path):
        return jsonify({"status": "error", "message": "No active plan"}), 404
        
    try:
        with open(active_path, 'r') as f:
            plan = json.load(f)
            
        recommendations = agent.recommend_grocery_checks(plan)
        
        # Save recommendations to the plan so they persist on refresh
        plan['pantry_recommendations'] = recommendations
        with open(active_path, 'w') as f:
            json.dump(plan, f, indent=4)
            
        return jsonify({"status": "ok", "recommendations": recommendations})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/plan/grocery/add_to_pantry', methods=['POST'])
def add_grocery_to_pantry():
    active_path = os.path.join(agent.state_dir, 'active_plan.json')
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
        count = inventory_manager.parse_and_add(raw_text)
        
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
def add_one_grocery_to_pantry():
    data = request.json
    ingredient_str = data.get('ingredient')
    item_id = data.get('item_id')
    
    if not ingredient_str:
        return jsonify({"status": "error", "message": "Missing ingredient"}), 400

    active_path = os.path.join(agent.state_dir, 'active_plan.json')
    
    try:
        success, message = inventory_manager.add_one_smartly(ingredient_str)
        
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

@app.route('/api/inventory/remove_by_recipe_item', methods=['POST'])
def remove_ingredient_from_cooking():
    data = request.json
    ingredient_str = data.get('ingredient')
    if not ingredient_str:
        return jsonify({"status": "error", "message": "Missing ingredient string"}), 400
        
    try:
        success, message = inventory_manager.remove_by_recipe_item(ingredient_str)
        if success:
            return jsonify({"status": "ok", "message": message})
        else:
            return jsonify({"status": "not_found", "message": message})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/cookbook')
def cookbook_page():
    from app.core.cookbook_manager import CATEGORIES, PROTEINS
    recipes = cookbook_manager.load_recipes()
    
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
        
    return render_template('cookbook.html', recipes=recipes, categories=CATEGORIES, proteins=PROTEINS)

# --- SYNC STATUS GLOBAL ---
SYNC_STATUS = {
    "is_syncing": False,
    "current": 0,
    "total": 0,
    "message": "Idle",
    "percent": 0,
    "cancel_requested": False
}

def run_sync_job():
    global SYNC_STATUS
    SYNC_STATUS["is_syncing"] = True
    SYNC_STATUS["cancel_requested"] = False
    SYNC_STATUS["message"] = "Starting sync..."
    
    def callback(curr, total, msg):
        global SYNC_STATUS
        SYNC_STATUS["current"] = curr
        SYNC_STATUS["total"] = total
        SYNC_STATUS["message"] = msg
        if total > 0:
            SYNC_STATUS["percent"] = int((curr / total) * 100)
            
    def check_cancel():
        return SYNC_STATUS.get("cancel_requested", False)
        
    try:
        # Use selected Librarian model (usually a Gemini model for PDF ingestion)
        librarian_id = agent.model_manager.get_librarian_model_id()
        print(f"DEBUG: Librarian Model: {librarian_id}")
        
        added_recipes = cookbook_manager.sync_library(progress_callback=callback, model_id=librarian_id, cancel_check=check_cancel)
        
        if SYNC_STATUS.get("cancel_requested"):
             SYNC_STATUS["message"] = "Sync Stopped."
             print("DEBUG: --- SYNC JOB STOPPED ---")
        else:
             if added_recipes:
                 # Join names, maybe truncate if too long
                 names_str = ", ".join(added_recipes)
                 if len(names_str) > 50:
                     names_str = names_str[:47] + "..."
                 SYNC_STATUS["message"] = f"Sync Complete! Added: {names_str}"
             else:
                 SYNC_STATUS["message"] = "Sync Complete! No new recipes found."
                 
             SYNC_STATUS["percent"] = 100
             print("DEBUG: --- SYNC JOB FINISHED ---")
             
    except Exception as e:
        SYNC_STATUS["message"] = f"Error: {e}"
        print(f"DEBUG: Sync Job Exception: {e}")
        import traceback
        traceback.print_exc()
    finally:
        time.sleep(1) # Let UI see message
        SYNC_STATUS["is_syncing"] = False
        SYNC_STATUS["cancel_requested"] = False

@app.route('/cookbook/sync', methods=['POST'])
def sync_cookbook():
    global SYNC_STATUS
    if SYNC_STATUS["is_syncing"]:
        return jsonify({"status": "already_running"}), 200
        
    # Start thread
    threading.Thread(target=run_sync_job).start()
    return jsonify({"status": "started"}), 200

@app.route('/cookbook/sync/cancel', methods=['POST'])
def cancel_sync():
    global SYNC_STATUS
    if SYNC_STATUS["is_syncing"]:
        SYNC_STATUS["cancel_requested"] = True
        return jsonify({"status": "cancel_requested"}), 200
    return jsonify({"status": "not_running"}), 200

@app.route('/cookbook/sync/status')
def sync_status():
    return jsonify(SYNC_STATUS)


from flask import send_from_directory

@app.route('/cookbook/pdf/<path:filename>')
def serve_recipe_pdf(filename):
    return send_from_directory(cookbook_manager.library_path, filename)

@app.route('/cookbook/add', methods=['GET', 'POST'])
def add_recipe():
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
        cookbook_manager.add_recipe(recipe_data)
        flash("Recipe added!", "success")
        return redirect('/cookbook')
    return render_template('recipe_form.html', categories=CATEGORIES, proteins=PROTEINS)

@app.route('/cookbook/edit/<recipe_id>', methods=['GET', 'POST'])
def edit_recipe(recipe_id):
    from app.core.cookbook_manager import CATEGORIES, PROTEINS
    if request.method == 'POST':
        updates = {
            "name": request.form.get('name'),
            "category": request.form.get('category'),
            "protein": request.form.get('protein'),
            "ingredients": request.form.get('ingredients').split('\n'),
            "instructions": request.form.get('instructions').split('\n'),
            "source": request.form.get('source')
        }
        cookbook_manager.update_recipe(recipe_id, updates)
        flash("Recipe updated!", "success")
        return redirect('/cookbook')
    
    recipe = cookbook_manager.get_recipe(recipe_id)
    if not recipe:
        flash("Recipe not found", "error")
        return redirect('/cookbook')
    return render_template('recipe_form.html', recipe=recipe, categories=CATEGORIES, proteins=PROTEINS)

@app.route('/cookbook/delete/<recipe_id>', methods=['POST'])
def delete_recipe(recipe_id):
    if cookbook_manager.delete_recipe(recipe_id):
        flash("Recipe deleted.", "success")
    else:
        flash("Error deleting recipe.", "error")
    return redirect('/cookbook')

@app.route('/cookbook/ignored')
def view_ignored_files():
    blacklist = cookbook_manager.load_blacklist()
    return render_template('ignored_files.html', blacklist=blacklist)

@app.route('/cookbook/restore/<path:filename>', methods=['POST'])
def restore_file(filename):
    if cookbook_manager.restore_ignored_file(filename):
        flash(f"Restored '{filename}'. It will be re-imported on next sync.", "success")
    else:
        flash("Error restoring file.", "error")
    return redirect('/cookbook/ignored')

@app.route('/cookbook/view/<recipe_id>')
def view_recipe(recipe_id):
    recipe = cookbook_manager.get_recipe(recipe_id)
    if not recipe:
        flash("Recipe not found", "error")
        return redirect('/cookbook')
    return render_template('recipe_detail.html', recipe=recipe)

@app.route('/api/cookbook/add_from_plan', methods=['POST'])
def save_from_plan_api():
    """API endpoint to save a recipe from a plan to the cookbook."""
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
        recipe = cookbook_manager.add_recipe(recipe_data)
        return jsonify({"status": "ok", "message": f"Saved {recipe.name} to cookbook!", "id": recipe.id})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/cookbook/rate', methods=['POST'])
def rate_recipe_endpoint():
    data = request.json
    if not data or not data.get('id') or data.get('rating') is None:
        return jsonify({"status": "error", "message": "Missing id or rating"}), 400
        
    try:
        rating = int(data.get('rating'))
        if rating < 0 or rating > 5:
             return jsonify({"status": "error", "message": "Rating must be 0-5"}), 400
             
        if cookbook_manager.rate_recipe(data.get('id'), rating):
            return jsonify({"status": "ok", "message": "Rated!"})
        else:
             return jsonify({"status": "error", "message": "Recipe not found"}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/cookbook/save_from_plan', methods=['POST'])
def save_from_plan_form():
    """Form-based version of saving from plan (redirects back)."""
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
        cookbook_manager.add_recipe(recipe_data)
        flash(f"Saved {name} to your Cookbook!", "success")
    except Exception as e:
        flash(f"Error saving recipe: {str(e)}", "error")
        
    return redirect(request.referrer or '/cookbook')

@app.route('/api/plan/active/rate_meal', methods=['POST'])
def rate_active_meal():
    data = request.json
    date_str = data.get('date')
    meal_type = data.get('meal_type')
    rating = int(data.get('rating', 0))
    
    active_path = os.path.join(agent.state_dir, 'active_plan.json')
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
                    recipes = cookbook_manager.load_recipes()
                    match = next((r for r in recipes if r['name'].lower() == meal['name'].lower()), None)
                    if match:
                        cookbook_manager.rate_recipe(match['id'], rating)
        
        with open(active_path, 'w') as f:
            json.dump(plan, f, indent=4)
            
        return jsonify({"status": "ok"})
    except Exception as e:
         return jsonify({"status": "error", "message": str(e)}), 500

# calendar_manager = CalendarManager(base_dir) # Consolidated into agent.calendar_manager

# --- COOKBOOK INIT (Must be after calendar_manager) ---
from app.core.cookbook_manager import CookbookManager
app_config = agent.calendar_manager.load_config()
cookbook_manager = CookbookManager(base_dir, app_config)

# Run migration on startup
try:
    cookbook_manager.initialize() 
except Exception as e:
    print(f"Cookbook Init Error: {e}")

# ... routes ...

import calendar

@app.route('/api/estimate', methods=['POST'])
def estimate_cost_endpoint():
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
def test_model_endpoint():
    model_id = request.json.get('model_id')
    status, msg = agent.model_manager.test_connection(model_id)
    return jsonify({"status": status, "msg": msg})

@app.route('/settings/core_model', methods=['POST'])
def update_core_model():
    model_id = request.form.get('core_model_id')
    if model_id:
        agent.model_manager.set_core_model(model_id)
        flash(f"Head Chef updated to {model_id}.", "success")
    return redirect('/settings')

@app.route('/settings/sous_chef_model', methods=['POST'])
def update_sous_chef_model():
    model_id = request.form.get('sous_chef_model_id')
    if model_id:
        agent.model_manager.set_sous_chef_model(model_id)
        flash(f"Sous Chef updated to {model_id}.", "success")
    return redirect('/settings')

@app.route('/settings/librarian_model', methods=['POST'])
def update_librarian_model():
    model_id = request.form.get('librarian_model_id')
    if model_id:
        agent.model_manager.set_librarian_model(model_id)
        flash(f"Librarian updated to {model_id}.", "success")
    return redirect('/settings')

@app.route('/calendar/widget')
def calendar_widget():
    """
    Returns a partial HTML for the calendar widget.
    Accepts 'date' (default: today), 'duration' (default: 4 or from config), and 'view' (default: custom range).
    """
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
        duration = int(duration_str)
    else:
        duration = config.get('duration_days', 4)

    # Reuse calendar manager logic from the global agent
    # We need to manually construct the "Custom Range" view since 'view_mode' logic is fixed.
    # Let's bypass get_days_for_view for this specific custom requirement or add a helper?
    # Actually, we can just use the Manager's logic if we update it, OR just replicate the dict construction here using the Manager's methods if they were granular.
    # Since get_days_for_view is monolithic, let's just create the list manually here for maximum control.
    
    events = cal_manager.load_calendar()
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    
    # Calculate visual plan window (It matches the requested range exactly)
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
            "in_plan_window": True, # Always true for this widget as we show ONLY the plan
            "content": content
        }
        calendar_days.append(day_data)

    return render_template(
        'calendar_partial.html',
        calendar_days=calendar_days,
        view_mode='custom', # Signal to template
        ref_date=ref_date,
        config=config
    )

@app.route('/settings/models/cost', methods=['POST'])
def update_model_cost():
    model_id = request.form.get('model_id')
    cost_in = request.form.get('cost_in')
    cost_out = request.form.get('cost_out')
    
    if model_id:
        agent.model_manager.update_model_cost(model_id, cost_in, cost_out)
        flash("Cost rates updated.", "success")
    return redirect('/settings')

@app.route('/calendar')
def calendar_page():
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

    # Get Next Run for Planning Window (Deterministic based on settings)
    next_run = agent.calendar_manager.get_next_run_dt()
    
    # Get Data from Manager
    calendar_days = agent.calendar_manager.get_days_for_view(ref_date, view_mode, next_run_dt=next_run)
    
    # Navigation Deltas (Simplified Logic locally or could be in manager too, but fine here)
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
    default_start_iso = default_start.strftime("%Y-%m-%d")

    # Identifiers for next 14 days (for settings select labels)
    days_data = []
    base = datetime.now()
    for i in range(14):
        d = base + timedelta(days=i)
        days_data.append({
            "day": d.strftime("%A"),
            "label": f"{d.strftime('%A')} ({d.strftime('%b %d')})"
        })

    # Get Models for Selector (for Generate Plan modal)
    available_models = agent.model_manager.get_available_models()
    current_model = next((m for m in available_models if m.get('is_core')), None)
    if not current_model:
         current_model = next((m for m in available_models if not m.get('locked')), None)

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
                           current_model=current_model)

@app.route('/calendar/settings', methods=['POST'])
def update_settings():
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
def set_duration():
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
def toggle_slot():
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
def api_update_schedule_settings():
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
def api_toggle_schedule():
    try:
        config = agent.calendar_manager.load_config()
        new_state = not config.get('schedule_enabled', True)
        config['schedule_enabled'] = new_state
        agent.calendar_manager.save_config(config)
        return jsonify({"status": "ok", "new_state": new_state})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/calendar/toggle', methods=['POST'])
def api_toggle_slot():
    """
    AJAX endpoint to toggle a meal slot on/off.
    json body: { "day": "Monday", "meal": "breakfast", "date": "optional YYYY-MM-DD" }
    """
    data = request.json
    day_name = data.get('day')
    meal_type = data.get('meal')
    date_str = data.get('date')
    
    if not day_name or not meal_type:
        return jsonify({"error": "Missing day or meal"}), 400
        
    # Reuse CalendarManager
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
def handle_ideas():
    ideas_path = os.path.join(agent.state_dir, 'ideas.txt')
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
