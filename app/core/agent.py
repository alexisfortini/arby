import os
import json
import time
import uuid
import google.genai as genai
from datetime import datetime, timedelta
from pydantic import BaseModel
from app.core.pdf_manager import PDFManager
from app.core.inventory_manager import InventoryManager
from app.core.mailer import Mailer
from app.core.calendar_manager import CalendarManager
from app.core.cookbook_manager import CookbookManager
from app.core.review_manager import ReviewManager

from app.core.schemas import WeeklyPlan, DayPlan, MealDetail, PantryRecommendations, AssistantActionResponse
from app.core.model_manager import ModelManager

class ArbyAgent:
    def __init__(self, base_dir, user_id, original_env=None):
        self.base_dir = base_dir
        self.user_id = user_id
        self.original_env = original_env
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
        prefs = {}
        if os.path.exists(self.pref_file):
            try:
                with open(self.pref_file, 'r') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        prefs = data
                        user_keys = prefs.get('api_keys', {})
                    else:
                        print(f"DEBUG: Prefs file {self.pref_file} is not a dict.")
            except Exception as e:
                print(f"DEBUG: Error loading prefs at {self.pref_file}: {e}")

        # Initialize Model Manager (User-Specific Keys)
        self.model_manager = ModelManager(base_dir=base_dir, user_id=self.user_id, original_env=self.original_env, user_keys=user_keys) 
        
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
            try:
                with open(self.history_file, 'r') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
                    print(f"DEBUG: History file {self.history_file} is not a list.")
            except Exception as e:
                print(f"DEBUG: Error loading history at {self.history_file}: {e}")
        return []

    def save_history(self, plan_dict):
        history = self.load_history()
        
        # Defensive check: plan_dict must be a dictionary
        if not isinstance(plan_dict, dict):
            print(f"DEBUG: save_history called with invalid plan_dict type: {type(plan_dict)}")
            return

        # Extract meals and ratings
        meals_executed = []
        for day in plan_dict.get('days', []):
            if not isinstance(day, dict): continue
            for mt in ['breakfast', 'lunch', 'dinner']:
                m = day.get(mt)
                if isinstance(m, dict):
                    meals_executed.append({
                        "name": m.get('name', 'Unknown Meal'),
                        "rating": m.get('rating', 0),
                        "source": m.get('source', 'chef'),
                        "scheduled_date": day.get('date'),
                        "meal_type": mt,
                        "recipe_id": m.get('recipe_id'),
                        "ingredients": m.get('ingredients', []),
                        "instructions": m.get('instructions', [])
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

    def clear_history(self):
        """Safely clears the history file."""
        with open(self.history_file, 'w') as f:
            json.dump([], f, indent=4)

    def construct_prompt(self, start_date=None, duration=None, target_slots=None, chef_user_ratio=50, ideas_override=None):
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
        
        # Determine Schedule Targets
        days_config_summary = []
        if target_slots:
            slot_map = {}
            for s in target_slots:
                if isinstance(s, dict):
                    d, m = s.get('date'), s.get('meal_type')
                elif isinstance(s, (list, tuple)) and len(s) == 2:
                    d, m = s[0], s[1]
                else:
                    continue
                if d and m:
                    slot_map.setdefault(d, []).append(m)
            for d_str, meals in sorted(slot_map.items()):
                try:
                    d_obj = datetime.strptime(d_str, "%Y-%m-%d")
                    day_name = d_obj.strftime("%A")
                except:
                    day_name = "Scheduled Day"
                days_config_summary.append(f"{day_name} ({d_str}): {', '.join(meals)}")
        else:
            if start_date:
                if isinstance(start_date, str):
                    try:
                        start_date = datetime.strptime(start_date, "%Y-%m-%d")
                    except:
                        start_date = datetime.now() + timedelta(days=1)
            else:
                today = datetime.now()
                start_date = today + timedelta(days=1)
                 
            days_to_plan = int(duration) if duration else config.get('duration_days', 4)
            for i in range(days_to_plan):
                d = start_date + timedelta(days=i)
                day_name = d.strftime("%A")
                date_str = d.strftime("%Y-%m-%d")
                day_sched = config['schedule'].get(day_name, {})
                if any(day_sched.values()):
                    meals_needed = [m for m, active in day_sched.items() if active]
                    days_config_summary.append(f"{day_name} ({date_str}): {', '.join(meals_needed)}")
        
        # User Ideas
        user_ideas = ideas_override if ideas_override is not None else "No specific cravings."
        if user_ideas == "No specific cravings." and data_ctx.get('use_ideas') and os.path.exists(self.ideas_file):
            with open(self.ideas_file, 'r') as f:
                content = f.read().strip()
                if content:
                    user_ideas = content
                    
        past_meals = "Not provided."
        if data_ctx.get('use_history'):
            depth = prefs.get('history_depth', 10)
            try:
                depth = int(depth)
            except:
                depth = 10
            past_meals = json.dumps(self.load_history()[-depth:])
        
        # Cookbook Context
        cookbook_summary = "Not provided (Disabled in settings)."
        if data_ctx.get('use_cookbook', True) and os.path.exists(self.cookbook_file):
            try:
                with open(self.cookbook_file, 'r') as f:
                    cookbook_data = json.load(f)
                    recipes_list = []
                    for r in cookbook_data:
                        rating_str = f" ({r.get('rating')} stars)" if r.get('rating') and r.get('rating') > 0 else ""
                        recipes_list.append(f"- {r['name']}{rating_str} ({r.get('protein', 'Veg')}) [ID: {r.get('id')}]")
                    cookbook_summary = "\n".join(recipes_list[:60])
            except:
                cookbook_summary = "Error loading cookbook library."
        
        # Chef vs Cookbook Recipe Ratio
        try:
            chef_ratio = int(chef_user_ratio) if chef_user_ratio is not None else 50
        except:
            chef_ratio = 50
        cookbook_ratio = 100 - chef_ratio
        
        ratio_instruction = (
            f"CHEF VS COOKBOOK RATIO: The user requests approximately {chef_ratio}% creative Chef recipes "
            f"and {cookbook_ratio}% recipes selected directly from their Cookbook Library below. Strictly adhere to this balance."
        )

        system_instruction = f"""
        You are Arby, an expert culinary assistant and meal planning chef.
        
        YOUR GOAL:
        Create or update meals with complete, delicious recipes for the specific dates and slots requested.
        
        CUSTOMER PREFERENCES:
        {long_term_prefs}
        
        {ratio_instruction}

        OUTPUT FORMAT:
        Return a JSON object matching the `WeeklyPlan` schema.
        - `days`: A list of objects, each containing a `date` (YYYY-MM-DD) and meal slots (breakfast, lunch, dinner).
        - **IMPORTANT**: Each filled meal slot MUST contain:
            - `name`: The exact dish name.
            - `ingredients`: Specific list of ingredients and quantities for that dish.
            - `instructions`: Clear step-by-step cooking instructions.
            - `source`: Set to "library" if taken from the Cookbook Library, or "chef" if it is a new/modified recipe.
            - `recipe_id`: If selected from the Cookbook Library, set to the library recipe ID.
        - `shopping_list`: Consolidated list of ingredients to purchase.
        - `summary_message`: A warm, friendly message from Chef Arby summarizing the meal lineup.
        
        CONSTRAINTS:
        1. Only fill the meal slots (Breakfast/Lunch/Dinner) specifically requested in the schedule below.
        2. Obey the User Ideas / Cravings provided below.
        3. Prioritize using stocked Inventory items where appropriate.
        4. Learn from History and Cookbook Ratings. Favor dishes with 4-5 stars. Avoid dishes with 1-2 stars unless specifically requested.
        """
        
        user_prompt = f"""
        **Requested Schedule & Slots:**
        {chr(10).join([f"- {s}" for s in days_config_summary]) if days_config_summary else "Plan meals according to standard schedule."}
        
        **User Ideas / Cravings:** {user_ideas}
        
        **Cookbook Library (User Recipes):**
        {cookbook_summary}
        
        **Available Inventory:** {inventory_summary}
        
        **Recent History:** {past_meals}
        """
        return system_instruction, user_prompt

    def generate_draft(self, model_id=None, start_date=None, duration=None, target_slots=None, chef_user_ratio=50, ideas_override=None):
        """Generates meals using the selected model with slot targets and chef ratio."""
        print(f"Starting Arby Run with Model: {model_id or 'Default'}...")
        system_instruction, user_prompt = self.construct_prompt(
            start_date=start_date, 
            duration=duration,
            target_slots=target_slots,
            chef_user_ratio=chef_user_ratio,
            ideas_override=ideas_override
        )
        
        if not model_id:
            model_id = self.model_manager.get_core_model_id()
            
        try:
            return self.model_manager.generate(
                model_id=model_id,
                system_instruction=system_instruction,
                user_prompt=user_prompt
            )
        except Exception as e:
            return {"error": f"Generation failed: {str(e)}"}

    def plan_slots(self, target_slots=None, model_id=None, start_date=None, duration=None, chef_user_ratio=50, ideas_override=None):
        """
        Plans meals specifically for the requested slots (or horizon),
        and directly updates calendar.json.
        """
        result = self.generate_draft(
            model_id=model_id,
            start_date=start_date,
            duration=duration,
            target_slots=target_slots,
            chef_user_ratio=chef_user_ratio,
            ideas_override=ideas_override
        )
        if isinstance(result, dict) and "error" in result:
            return result

        # Directly update calendar.json with the generated meals!
        for day in result.get('days', []):
            d_str = day.get('date')
            if not d_str:
                continue
            for mt in ['breakfast', 'lunch', 'dinner']:
                meal = day.get(mt)
                if meal and isinstance(meal, dict) and meal.get('name'):
                    self.calendar_manager.set_meal(d_str, mt, {
                        "name": meal.get('name'),
                        "recipe_id": meal.get('recipe_id'),
                        "source": meal.get('source', 'chef'),
                        "ingredients": meal.get('ingredients', []),
                        "instructions": meal.get('instructions', []),
                        "image_url": meal.get('image_url'),
                        "completed": False,
                        "rating": meal.get('rating', 0)
                    })

        # Auto-pantry check recommendations if any
        try:
            recommendations = self.recommend_grocery_checks(result)
            result['pantry_recommendations'] = recommendations
        except Exception as e:
            print(f"Pantry check recommendation error: {e}")

        return result

    def stream_plan_slots(self, target_slots=None, model_id=None, start_date=None, duration=None, chef_user_ratio=50, ideas_override=None):
        """
        Yields real-time harness progress events as a generator.
        Final event yields status: 'completed' with redirect: '/plan/view'.
        """
        import time
        if not model_id:
            model_id = self.model_manager.get_core_model_id()
            
        model_name = model_id
        for m in self.model_manager.get_available_models():
            if m['id'] == model_id:
                model_name = m.get('name', model_id)
                break

        # Step 1: Inventory
        yield {
            "step": 1,
            "progress": 15,
            "stage": "inventory",
            "message": "Scanning pantry inventory..."
        }
        time.sleep(0.15)
        inv_items = self.inventory_manager.load_inventory()
        inv_count = len(inv_items) if isinstance(inv_items, list) else 0
        yield {
            "step": 1,
            "progress": 25,
            "stage": "inventory",
            "message": f"Scanned pantry: found {inv_count} stocked items to prioritize."
        }
        time.sleep(0.15)

        # Step 2: Cookbook & History
        yield {
            "step": 2,
            "progress": 40,
            "stage": "cookbook",
            "message": "Reviewing cookbook favorites & recent meal history..."
        }
        recipes = self.cookbook_manager.load_recipes()
        fav_count = len([r for r in recipes if r.get('rating', 0) >= 4])
        yield {
            "step": 2,
            "progress": 50,
            "stage": "cookbook",
            "message": f"Loaded {len(recipes)} recipes ({fav_count} top-rated favorites prioritized, avoiding recent repeats)."
        }
        time.sleep(0.15)

        # Step 3: Dietary Rules & Ratios
        chef_ratio = int(chef_user_ratio) if chef_user_ratio is not None else 50
        cookbook_ratio = 100 - chef_ratio
        yield {
            "step": 3,
            "progress": 65,
            "stage": "preferences",
            "message": f"Applying cravings & dietary profile ({chef_ratio}% Chef / {cookbook_ratio}% Cookbook Library)..."
        }
        time.sleep(0.15)

        # Step 4: Prompting Model
        yield {
            "step": 4,
            "progress": 75,
            "stage": "generation",
            "message": f"Calling {model_name} to craft personalized recipes and ingredients..."
        }

        # Real LLM Call!
        system_instruction, user_prompt = self.construct_prompt(
            start_date=start_date,
            duration=duration,
            target_slots=target_slots,
            chef_user_ratio=chef_user_ratio,
            ideas_override=ideas_override
        )
        
        try:
            result = self.model_manager.generate(
                model_id=model_id,
                system_instruction=system_instruction,
                user_prompt=user_prompt
            )
        except Exception as e:
            yield {
                "step": 4,
                "progress": 75,
                "status": "error",
                "message": f"Generation failed: {str(e)}"
            }
            return

        if isinstance(result, dict) and "error" in result:
            yield {
                "step": 4,
                "progress": 75,
                "status": "error",
                "message": result["error"]
            }
            return

        # Step 5: Committing to Calendar & Schedule
        yield {
            "step": 5,
            "progress": 90,
            "stage": "saving",
            "message": "Validating meals and saving to your calendar..."
        }
        
        meal_count = 0
        for day in result.get('days', []):
            d_str = day.get('date')
            if not d_str:
                continue
            for mt in ['breakfast', 'lunch', 'dinner']:
                meal = day.get(mt)
                if meal and isinstance(meal, dict) and meal.get('name'):
                    meal_count += 1
                    self.calendar_manager.set_meal(d_str, mt, {
                        "name": meal.get('name'),
                        "recipe_id": meal.get('recipe_id'),
                        "source": meal.get('source', 'chef'),
                        "ingredients": meal.get('ingredients', []),
                        "instructions": meal.get('instructions', []),
                        "image_url": meal.get('image_url'),
                        "completed": False,
                        "rating": meal.get('rating', 0)
                    })

        try:
            recommendations = self.recommend_grocery_checks(result)
            result['pantry_recommendations'] = recommendations
        except Exception as e:
            print(f"Pantry check recommendation error: {e}")

        # Complete!
        yield {
            "step": 6,
            "progress": 100,
            "status": "completed",
            "redirect": "/plan/view",
            "message": f"Success! {meal_count} meals saved to your calendar."
        }

    def load_custom_groceries(self):
        p = os.path.join(self.user_state_dir, 'custom_groceries.json')
        if os.path.exists(p):
            try:
                with open(p, 'r') as f:
                    return json.load(f)
            except:
                return []
        return []

    def save_custom_groceries(self, items):
        p = os.path.join(self.user_state_dir, 'custom_groceries.json')
        with open(p, 'w') as f:
            json.dump(items, f, indent=4)

    def add_custom_groceries(self, new_items):
        existing = self.load_custom_groceries()
        for it in new_items:
            if isinstance(it, str) and it.strip():
                existing.append({"id": f"custom-{uuid.uuid4().hex[:8]}", "name": it.strip(), "checked": False})
            elif isinstance(it, dict) and it.get('name'):
                existing.append(it)
        self.save_custom_groceries(existing)
        return existing

    def execute_assistant_command(self, user_message: str):
        """
        Interprets natural language commands from the floating assistant chat
        and executes corresponding actions on calendar, recipes, or grocery list.
        """
        today = datetime.now().date()
        today_str = today.strftime("%Y-%m-%d")
        upcoming = self.calendar_manager.get_upcoming_meals(today, days_ahead=7)
        schedule_summary = []
        for m in upcoming:
            schedule_summary.append(f"{m['date']} ({m['meal_title']}): {m['name']} {'[Cooked]' if m['completed'] else ''}")

        recipes = self.cookbook_manager.load_recipes()
        recipe_names = [r['name'] for r in recipes[:30]]

        system_instruction = f"""
        You are Arby, the intelligent kitchen companion and personal culinary assistant.
        Today's date is {today_str} ({today.strftime('%A')}).

        CURRENT UPCOMING SCHEDULE (Next 7 days):
        {chr(10).join(schedule_summary) if schedule_summary else "No upcoming meals currently scheduled."}

        USER'S COOKBOOK RECIPES (Sample):
        {', '.join(recipe_names) if recipe_names else "Cookbook is empty."}

        CAPABILITIES & ACTIONS:
        You can answer culinary questions directly OR trigger actions by setting `action_type` and `action_payload`:
        1. `plan_slots`: When user asks to plan a meal or meals (e.g. "plan dinner tomorrow", "what should I make for lunch on Friday?").
           - `action_payload`: {{ "slots": [{{"date": "YYYY-MM-DD", "meal_type": "breakfast|lunch|dinner"}}], "cravings": "user notes or desires" }}
        2. `swap_meals`: When user asks to swap two meals (e.g. "swap tonight's dinner with tomorrow's").
           - `action_payload`: {{ "date1": "YYYY-MM-DD", "meal1": "dinner", "date2": "YYYY-MM-DD", "meal2": "dinner" }}
        3. `set_meal`: When user explicitly assigns a specific dish to a slot (e.g. "put Grilled Salmon for tomorrow night's dinner").
           - `action_payload`: {{ "date": "YYYY-MM-DD", "meal_type": "dinner", "name": "Grilled Salmon", "source": "user" }}
        4. `clear_meal`: When user asks to remove/cancel a meal (e.g. "clear Friday lunch").
           - `action_payload`: {{ "date": "YYYY-MM-DD", "meal_type": "lunch" }}
        5. `mark_cooked`: When user cooked a meal (e.g. "I just finished cooking tonight's dinner").
           - `action_payload`: {{ "date": "YYYY-MM-DD", "meal_type": "dinner" }}
        6. `add_grocery`: When user wants to add items to grocery list (e.g. "add almond milk and eggs to my list").
           - `action_payload`: {{ "items": ["almond milk", "eggs"] }}
        7. `none`: When answering a general question, cooking advice, substitute idea, or greeting.
           - `action_payload`: {{}}

        Respond with a warm, helpful, professional culinary message in `reply`.
        """

        model_id = self.model_manager.get_sous_chef_model_id() or self.model_manager.get_core_model_id()
        try:
            action_res = self.model_manager.generate(
                model_id=model_id,
                system_instruction=system_instruction,
                user_prompt=user_message,
                schema=AssistantActionResponse
            )
            
            action_type = action_res.get('action_type', 'none')
            payload = action_res.get('action_payload', {})
            reply = action_res.get('reply', "Done!")
            
            # Execute action
            if action_type == "plan_slots":
                slots = payload.get('slots', [])
                cravings = payload.get('cravings')
                if slots:
                    self.plan_slots(target_slots=slots, ideas_override=cravings)
            elif action_type == "swap_meals":
                d1, m1 = payload.get('date1'), payload.get('meal1')
                d2, m2 = payload.get('date2'), payload.get('meal2')
                if d1 and m1 and d2 and m2:
                    self.calendar_manager.swap_meals(d1, m1, d2, m2)
            elif action_type == "set_meal":
                d, m, name = payload.get('date'), payload.get('meal_type'), payload.get('name')
                if d and m and name:
                    matched = self.cookbook_manager.find_recipe_by_name(name)
                    if matched:
                        meal_dict = {
                            "name": matched['name'],
                            "recipe_id": matched['id'],
                            "source": "library",
                            "ingredients": matched.get('ingredients', []),
                            "instructions": matched.get('instructions', []),
                            "image_url": matched.get('image_url')
                        }
                    else:
                        meal_dict = {"name": name, "source": "user", "ingredients": [], "instructions": []}
                    self.calendar_manager.set_meal(d, m, meal_dict)
            elif action_type == "clear_meal":
                d, m = payload.get('date'), payload.get('meal_type')
                if d and m:
                    self.calendar_manager.remove_meal(d, m)
            elif action_type == "mark_cooked":
                d, m = payload.get('date'), payload.get('meal_type')
                if d and m:
                    self.calendar_manager.mark_meal_completed(d, m, completed=True)
            elif action_type == "add_grocery":
                items = payload.get('items', [])
                if items:
                    self.add_custom_groceries(items)

            return {
                "status": "ok",
                "reply": reply,
                "action_type": action_type,
                "action_payload": payload
            }
        except Exception as e:
            print(f"Assistant command execution error: {e}")
            return {
                "status": "error",
                "reply": f"Sorry, I had trouble processing that: {str(e)}",
                "action_type": "none"
            }

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
            return self.model_manager.generate(
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
            day_content = existing_calendar.get(date_str, {})
            # Defensive check: if it's a string (legacy), start fresh or convert
            if isinstance(day_content, dict):
                day_state = day_content.copy()
            else:
                day_state = {}
            
            # Overlay new recipes only if they were provided in the new plan
            if day.get('breakfast'):
                day_state['breakfast'] = {
                    "name": day['breakfast']['name'],
                    "recipe_id": day['breakfast'].get('recipe_id'),
                    "source": day['breakfast'].get('source', 'chef'),
                    "ingredients": day['breakfast'].get('ingredients', []),
                    "instructions": day['breakfast'].get('instructions', [])
                }
            if day.get('lunch'):
                day_state['lunch'] = {
                    "name": day['lunch']['name'],
                    "recipe_id": day['lunch'].get('recipe_id'),
                    "source": day['lunch'].get('source', 'chef'),
                    "ingredients": day['lunch'].get('ingredients', []),
                    "instructions": day['lunch'].get('instructions', [])
                }
            if day.get('dinner'):
                day_state['dinner'] = {
                    "name": day['dinner']['name'],
                    "recipe_id": day['dinner'].get('recipe_id'),
                    "source": day['dinner'].get('source', 'chef'),
                    "ingredients": day['dinner'].get('ingredients', []),
                    "instructions": day['dinner'].get('instructions', [])
                }
            
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
            
            result = self.model_manager.generate(
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
