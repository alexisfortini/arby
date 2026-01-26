import os
import json
import time
import google.genai as genai
from datetime import datetime, timedelta
from pydantic import BaseModel
from app.core.pdf_manager import PDFManager
from app.core.inventory_manager import InventoryManager
from app.core.mailer import Mailer
from app.core.calendar_manager import CalendarManager
from app.core.cookbook_manager import CookbookManager
from app.core.review_manager import ReviewManager

from app.core.schemas import WeeklyPlan, DayPlan, MealDetail, PantryRecommendations
from app.core.model_manager import ModelManager

class ArbyAgent:
    def __init__(self, base_dir, user_id):
        self.base_dir = base_dir
        self.user_id = user_id
        # Strict User Isolation
        self.user_state_dir = os.path.join(base_dir, 'state', 'users', user_id)
        
        # Ensure user dir exists (in case created manually or migration lag)
        os.makedirs(self.user_state_dir, exist_ok=True)
        
        self.pdf_folder = os.environ.get("PDF_FOLDER")
        
        self.cookbook_file = os.path.join(self.user_state_dir, 'cookbook.json')
        
        # Ideas and Prefs are also strictly isolated
        self.ideas_file = os.path.join(self.user_state_dir, 'ideas.txt')
        self.pref_file = os.path.join(self.user_state_dir, 'preferences.json')

        # Load Prefs early for Model Manager
        user_keys = {}
        if os.path.exists(self.pref_file):
            try:
                with open(self.pref_file, 'r') as f:
                    prefs = json.load(f)
                    user_keys = prefs.get('api_keys', {})
            except:
                pass

        # Initialize Model Manager (User-Specific Keys)
        self.model_manager = ModelManager(base_dir=base_dir, original_env=None, user_keys=user_keys) 
        
        self.inventory_manager = InventoryManager(
            inventory_file=os.path.join(self.user_state_dir, 'inventory.json'),
            model_manager=self.model_manager
        )
        self.calendar_manager = CalendarManager(self.user_state_dir)
        
        self.cookbook_manager = CookbookManager(self.user_state_dir, config={}) # Config loaded internally or passed if needed
        self.review_manager = ReviewManager(self.user_state_dir, model_manager=self.model_manager)
        
        # Prepare Mailer with User-Specific Settings
        email_config = prefs.get('email_settings', {})
        
        def resolve(val):
            return self.model_manager._resolve_key(val) if val else val

        mailer_config = {
            "EMAIL_SENDER": resolve(email_config.get('sender')),
            "EMAIL_PASSWORD": resolve(email_config.get('password')),
            "EMAIL_RECEIVER": email_config.get('receivers') # Receivers don't usually need pointer resolving
        }
        self.mailer = Mailer(config=mailer_config)
        
        self.history_file = os.path.join(self.user_state_dir, 'history.json')
        self.blacklist_file = os.path.join(self.user_state_dir, 'blacklist.json')

    def load_history(self):
        if os.path.exists(self.history_file):
            with open(self.history_file, 'r') as f:
                return json.load(f)
        return []

    def save_history(self, plan_dict):
        history = self.load_history()
        
        # Extract meals and ratings
        meals_executed = []
        for day in plan_dict.get('days', []):
            for mt in ['breakfast', 'lunch', 'dinner']:
                m = day.get(mt)
                if m:
                    meals_executed.append({
                        "name": m['name'],
                        "rating": m.get('rating', 0),
                        "source": m.get('source', 'chef')
                    })

        entry = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "summary": plan_dict.get('summary_message', ''),
            "meals": meals_executed
        }
        history.append(entry)
        
        # Keep history manageable (e.g. last 100 plans)
        if len(history) > 100:
            history = history[-100:]
            
        with open(self.history_file, 'w') as f:
            json.dump(history, f, indent=4)

    def construct_prompt(self, start_date=None, duration=None):
        """Constructs the system and user prompts based on current state."""
        # Load Preferences
        pref_path = self.pref_file
        prefs = {}
        if os.path.exists(pref_path):
            with open(pref_path, 'r') as f:
                prefs = json.load(f)
        
        data_ctx = prefs.get('data_context', {
            "use_inventory": True,
            "use_history": True,
            "use_blacklist": True,
            "use_ideas": True,
            "use_cookbook": True
        })
        long_term_prefs = prefs.get('long_term_preferences', "No long-term preferences set.")

        # 1. Sync & Inventory & Config
        inventory_summary = "Not provided."
        if data_ctx.get('use_inventory'):
            inventory_summary = self.inventory_manager.get_summary()
        
        # Get Config
        config = self.calendar_manager.load_config()
        
        # Determine Start Date
        if start_date:
            if isinstance(start_date, str):
                 start_date = datetime.strptime(start_date, "%Y-%m-%d")
        else:
             today = datetime.now()
             start_date = today + timedelta(days=1)
             
        # Determine Duration
        days_to_plan = int(duration) if duration else config.get('duration_days', 4)
        
        planning_dates = []
        days_config_summary = []
        for i in range(days_to_plan):
            d = start_date + timedelta(days=i)
            day_name = d.strftime("%A")
            date_str = d.strftime("%Y-%m-%d")
            day_sched = config['schedule'].get(day_name, {})
            if any(day_sched.values()):
                planning_dates.append(date_str)
                meals_needed = [m for m, active in day_sched.items() if active]
                days_config_summary.append(f"{day_name} ({date_str}): {', '.join(meals_needed)}")
        
        # User Context
        user_ideas = "No specific cravings."
        if data_ctx.get('use_ideas') and os.path.exists(self.ideas_file):
            with open(self.ideas_file, 'r') as f:
                user_ideas = f.read().strip()
                
        past_meals = "Not provided."
        if data_ctx.get('use_history'):
            depth = prefs.get('history_depth', 50)
            try:
                depth = int(depth)
            except:
                depth = 50
            past_meals = json.dumps(self.load_history()[-depth:])
        
        # Cookbook Context
        cookbook_summary = "Not provided (Disabled in settings)."
        if data_ctx.get('use_cookbook', True) and os.path.exists(self.cookbook_file):
            try:
                with open(self.cookbook_file, 'r') as f:
                    cookbook_data = json.load(f)
                    # Provide a condensed list of available recipes to the chef with ratings
                    recipes_list = []
                    for r in cookbook_data:
                        rating_str = f" ({r.get('rating')} stars)" if r.get('rating') and r.get('rating') > 0 else ""
                        recipes_list.append(f"- {r['name']}{rating_str} ({r.get('protein', 'Veg')})")
                    cookbook_summary = "\n".join(recipes_list[:50]) # Limit to 50 for prompt size
            except:
                cookbook_summary = "Error loading cookbook library."
        
        system_instruction = f"""
        You are Arby, an expert meal planning chef.
        
        YOUR GOAL:
        Create a detailed meal plan with full recipes for specific dates.
        
        CUSTOMER PREFERENCES:
        {long_term_prefs}
        
        OUTPUT FORMAT:
        Return a JSON object matching the `WeeklyPlan` schema.
        - `days`: A list of objects, each containing a `date` and meal slots (breakfast, lunch, dinner).
        - **IMPORTANT**: Each meal slot MUST contain:
            - `name`: The name of the dish.
            - `ingredients`: A specific list of ingredients and quantities for that dish.
            - `instructions`: Step-by-step cooking instructions.
            - `source`: Set to "library" if the recipe is strictly from the Cookbook Library, or "chef" if it is a new recipe or heavily modified.
        - `shopping_list`: A consolidated master list of ALL ingredients to buy for the week.
        - `summary_message`: A friendly summary of the plan (the chef's notes). Should be a full paragraph.
        
        CONSTRAINTS:
        1. Only fill the meal slots (Breakfast/Lunch/Dinner) requested by the user for each date.
        2. Take inspiration from recipes in the Cookbook Library (provided below) if they fit the schedule and inventory. If you use a library recipe, you can adjust quantities to fit the requested servings.
        3. Obey the User Ideas (provided below) for the plan into account when planning the meals.
        4. Prioritize using Inventory items (provided below).
        5. Learn what the user likes based on the Recent History and Cookbook Ratings. Favor recipes with 4 or 5 stars. If a recipe has a low rating (1 or 2 stars), avoid using it unless specifically asked. Do not repeat the same recipes too often.
        """
        
        user_prompt = f"""
        **Planning Schedule:**
        Please plan meals for these days, respecting the specific meal slots requested:
        
        **Daily Requirements:**
        {chr(10).join([f"- {s}" for s in days_config_summary])}
        
        **User Ideas:** {user_ideas}
        
        **Your Cookbook Library (Preferred Sources):**
        {cookbook_summary}
        
        **Inventory Items:** {inventory_summary}
        
        **Recent History:** {past_meals}
        """
        return system_instruction, user_prompt

    def generate_draft(self, model_id=None, start_date=None, duration=None):
        """Generates a Meal Plan Draft using the selected model."""
        print(f"Starting Arby Run with Model: {model_id or 'Default'}...")
        
        # 1. Construct Prompt
        system_instruction, user_prompt = self.construct_prompt(start_date=start_date, duration=duration)
        
        # 7. Call Model Manager
        # Default to Configured Core Model if no model selected
        if not model_id:
            model_id = self.model_manager.get_core_model_id()
            
        try:
            return self.model_manager.generate_plan(
                model_id=model_id,
                system_instruction=system_instruction,
                user_prompt=user_prompt
            )
        except Exception as e:
            return {"error": f"Generation failed: {str(e)}"}

    def modify_plan(self, current_plan, user_feedback, model_id=None):
        """Modifies an existing plan based heavily on user feedback."""
        print(f"Modifying Plan with Model: {model_id or 'Default'}...")
        
        # 1. System Instruction - Focused on Modification
        system_instruction = """
        You are Arby, an expert meal planning chef.
        
        YOUR GOAL:
        Modify the provided meal plan based on the USER'S FEEDBACK.
        
        RULES:
        1. Keep everything that the user DID NOT ask to change.
        2. Strictly follow the user's new requirements (e.g. "change Tuesday dinner to Tacos").
        3. If the user asks for a recipe change, ensure you provide the FULL recipe details (ingredients, instructions) for the new dish.
        4. Re-generate the `shopping_list` to match the new set of meals perfectly.
        5. Update the `summary_message` to briefly address the user and mention the changes made.
        6. For each meal, set the `source` field to "library" if it is from the Cookbook Library, or "chef" if it is new/modified.
        
        OUTPUT FORMAT:
        Return a JSON object matching the `WeeklyPlan` schema (same structure as input).
        """
        
        # 2. User Prompt
        user_prompt = f"""
        **Current Plan (JSON):**
        {json.dumps(current_plan)}
        
        **User Feedback / Requested Changes:**
        "{user_feedback}"
        
        Please apply these changes and return the updated plan JSON.
        """
        
        # 3. Call Model
        if not model_id:
            model_id = self.model_manager.get_core_model_id()
            
        try:
            return self.model_manager.generate_plan(
                model_id=model_id,
                system_instruction=system_instruction,
                user_prompt=user_prompt
            )
        except Exception as e:
            return {"error": f"Modification failed: {str(e)}"}

    def finalize_plan(self, plan_dict):
        """Saves the plan to calendar, history, and sends email."""
        print("Finalizing Plan...")
        
        # 8. Save Data
        # Update Calendar
        calendar_update = {}
        # Load existing calendar to avoid wiping out preserved meals
        existing_calendar = self.calendar_manager.load_calendar()
        
        for day in plan_dict['days']:
            date_str = day['date']
            # Start with existing data for this date
            day_state = existing_calendar.get(date_str, {}).copy()
            
            # Overlay new recipes only if they were provided in the new plan
            if day.get('breakfast'):
                day_state['breakfast'] = day['breakfast']['name']
            if day.get('lunch'):
                day_state['lunch'] = day['lunch']['name']
            if day.get('dinner'):
                day_state['dinner'] = day['dinner']['name']
            
            calendar_update[date_str] = day_state
        
        self.calendar_manager.update_calendar(calendar_update)
        
        # Save History
        self.save_history(plan_dict)
        
        # 9. Email
        print("Sending Email...")
        self.mailer.send_detailed_plan(plan_dict)
        
        print("Finalization Complete.")
        return True

    def recommend_grocery_checks(self, plan_dict):
        """Cross-references grocery list with pantry and returns recommended item_ids to skip."""
        inventory_summary = self.inventory_manager.get_summary()
        
        # Flatten all ingredients into a list with their IDs
        flattened_items = []
        for day in plan_dict['days']:
            for meal_type in ['breakfast', 'lunch', 'dinner']:
                meal = day.get(meal_type)
                if meal:
                    for idx, ing in enumerate(meal['ingredients']):
                        item_id = f"{day['date']}-{meal_type}-{idx}"
                        flattened_items.append({"id": item_id, "name": ing})

        if not flattened_items or "Pantry is empty" in inventory_summary:
            return []

        system_instruction = """
        You are a meticulous Sous Chef. 
        Your task is to review a user's grocery list against their pantry inventory.
        
        Rules:
        1. Identify any grocery items that the user LIKELY already has in their pantry.
        2. Account for fuzzy matches (e.g., "1 Yellow Onion" likely matches "Onions").
        3. Be conservative—if you aren't sure there is ENOUGH of an item, don't recommend checking it off.
        4. Focus on staples and non-perishables (Spices, Oils, Grains).
        5. Return a list of ONLY the `item_id`s for ingredients that should be checked off.
        """
        
        user_prompt = f"""
        **Pantry Inventory:**
        {inventory_summary}
        
        **Grocery List:**
        {json.dumps(flattened_items)}
        """

        try:
            # Use the Sous Chef model if set
            model_id = self.model_manager.get_sous_chef_model_id()
            
            result = self.model_manager.generate_plan(
                model_id=model_id,
                system_instruction=system_instruction,
                user_prompt=user_prompt,
                schema=PantryRecommendations
            )
            return result.get('recommended_checks', [])
        except Exception as e:
            print(f"Error recommending grocery checks: {e}")
            return []

    def run(self):
        """Orchestrates the meal plan generation (Legacy/Background)."""
        print("Starting Automated Arby Run...")
        draft = self.generate_draft() # Uses default model
        if isinstance(draft, dict) and "error" in draft:
            print(f"Automated run failed: {draft['error']}")
            return "Failed"
        
        self.finalize_plan(draft)
        return "Run Complete"
