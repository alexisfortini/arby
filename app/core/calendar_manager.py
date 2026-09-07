import os
import json
import calendar
from datetime import datetime, timedelta, date, time as dt_time

class CalendarManager:
    def __init__(self, state_dir):
        self.state_dir = state_dir
        self.calendar_file = os.path.join(state_dir, 'calendar.json')
        self.config_file = os.path.join(state_dir, 'schedule_config.json')

    def load_calendar(self):
        if os.path.exists(self.calendar_file):
            try:
                with open(self.calendar_file, 'r') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return data
            except Exception as e:
                print(f"DEBUG: Error loading calendar at {self.calendar_file}: {e}")
        return {}
        
    def save_calendar(self, data):
        # Merge with existing? For now, we assume we load -> modify -> save
        with open(self.calendar_file, 'w') as f:
            json.dump(data, f, indent=4)
            
    def update_calendar(self, new_plan_json):
        """
        Updates the calendar with a new generated plan.
        new_plan_json: dict { "YYYY-MM-DD": { "breakfast": "...", ... } }
        """
        calendar = self.load_calendar()
        calendar.update(new_plan_json)
        self.save_calendar(calendar)

    def remove_meal(self, date_str, meal_type):
        """
        Removes a specific meal from a date in the calendar.
        """
        calendar = self.load_calendar()
        if date_str in calendar and meal_type in calendar[date_str]:
            del calendar[date_str][meal_type]
            # If date is now empty, remove it entirely
            if not calendar[date_str]:
                del calendar[date_str]
            self.save_calendar(calendar)

    def remove_day(self, date_str):
        """Removes an entire day's entries from the calendar."""
        calendar = self.load_calendar()
        if date_str in calendar:
            del calendar[date_str]
            self.save_calendar(calendar)

    def migrate_active_plan_if_needed(self):
        """
        Migrates legacy active_plan.json into calendar.json if present,
        ensuring all existing meals are preserved in the single source of truth.
        """
        active_plan_path = os.path.join(self.state_dir, 'active_plan.json')
        if os.path.exists(active_plan_path):
            try:
                with open(active_plan_path, 'r') as f:
                    plan = json.load(f)
                calendar = self.load_calendar()
                changed = False
                for day in plan.get('days', []):
                    date_str = day.get('date')
                    if not date_str:
                        continue
                    if date_str not in calendar:
                        calendar[date_str] = {}
                    for mt in ['breakfast', 'lunch', 'dinner']:
                        meal = day.get(mt)
                        if meal and isinstance(meal, dict) and meal.get('name'):
                            if mt not in calendar[date_str]:
                                calendar[date_str][mt] = {
                                    "name": meal.get('name'),
                                    "recipe_id": meal.get('recipe_id'),
                                    "source": meal.get('source', 'chef'),
                                    "ingredients": meal.get('ingredients', []),
                                    "instructions": meal.get('instructions', []),
                                    "image_url": meal.get('image_url'),
                                    "completed": meal.get('completed', False),
                                    "rating": meal.get('rating', 0)
                                }
                                changed = True
                if changed:
                    self.save_calendar(calendar)
                archived_path = os.path.join(self.state_dir, 'active_plan.json.migrated')
                if os.path.exists(archived_path):
                    os.remove(archived_path)
                os.replace(active_plan_path, archived_path)
                print(f"Migrated active_plan.json to calendar.json in {self.state_dir}")
            except Exception as e:
                print(f"Error migrating active_plan.json: {e}")

    def set_meal(self, date_str, meal_type, meal_data):
        """
        Sets or updates an individual meal slot.
        meal_data can be a dict or string name.
        """
        calendar = self.load_calendar()
        if date_str not in calendar:
            calendar[date_str] = {}
        if isinstance(meal_data, str):
            meal_data = {"name": meal_data, "source": "chef", "completed": False}
        elif isinstance(meal_data, dict):
            if "completed" not in meal_data:
                meal_data["completed"] = False
        calendar[date_str][meal_type] = meal_data
        self.save_calendar(calendar)
        return True

    def swap_meals(self, date1, meal_type1, date2, meal_type2):
        """Swaps two meal slots between dates/types."""
        calendar = self.load_calendar()
        meal1 = calendar.get(date1, {}).get(meal_type1)
        meal2 = calendar.get(date2, {}).get(meal_type2)

        if date1 not in calendar:
            calendar[date1] = {}
        if meal2:
            calendar[date1][meal_type1] = meal2
        elif meal_type1 in calendar[date1]:
            del calendar[date1][meal_type1]

        if date2 not in calendar:
            calendar[date2] = {}
        if meal1:
            calendar[date2][meal_type2] = meal1
        elif meal_type2 in calendar[date2]:
            del calendar[date2][meal_type2]

        for d in [date1, date2]:
            if d in calendar and not calendar[d]:
                del calendar[d]

        self.save_calendar(calendar)
        return True

    def mark_meal_completed(self, date_str, meal_type, completed=True):
        """Marks a meal slot as completed (cooked) and logs to history."""
        calendar = self.load_calendar()
        if date_str in calendar and meal_type in calendar[date_str]:
            meal = calendar[date_str][meal_type]
            if isinstance(meal, dict):
                meal['completed'] = completed
                self.save_calendar(calendar)
                if completed:
                    self._log_meal_to_history(date_str, meal_type, meal)
                return True
        return False

    def _log_meal_to_history(self, date_str, meal_type, meal):
        history_path = os.path.join(self.state_dir, 'history.json')
        history = []
        if os.path.exists(history_path):
            try:
                with open(history_path, 'r') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        history = data
            except:
                history = []

        entry = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "summary": f"Cooked {meal.get('name', 'Meal')}",
            "meals": [{
                "name": meal.get('name'),
                "rating": meal.get('rating', 0),
                "source": meal.get('source', 'chef'),
                "scheduled_date": date_str,
                "meal_type": meal_type,
                "recipe_id": meal.get('recipe_id'),
                "ingredients": meal.get('ingredients', []),
                "instructions": meal.get('instructions', [])
            }]
        }
        history.append(entry)
        if len(history) > 100:
            history = history[-100:]
        try:
            with open(history_path, 'w') as f:
                json.dump(history, f, indent=4)
        except Exception as e:
            print(f"Error logging meal to history: {e}")

    def get_upcoming_meals(self, start_date=None, days_ahead=30):
        """
        Returns a sorted list of upcoming meals from start_date (default today)
        up to days_ahead into the future.
        """
        self.migrate_active_plan_if_needed()
        calendar = self.load_calendar()
        today = datetime.now().date()
        if not start_date:
            start_date = today
        elif isinstance(start_date, str):
            try:
                start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
            except:
                start_date = today
        elif isinstance(start_date, datetime):
            start_date = start_date.date()

        end_date = start_date + timedelta(days=days_ahead)

        upcoming = []
        sorted_dates = sorted(calendar.keys())
        for d_str in sorted_dates:
            try:
                d_obj = datetime.strptime(d_str, "%Y-%m-%d").date()
            except:
                continue
            if d_obj < start_date or d_obj > end_date:
                continue

            day_data = calendar[d_str]
            if not isinstance(day_data, dict):
                continue

            for mt in ['breakfast', 'lunch', 'dinner']:
                meal = day_data.get(mt)
                if meal and isinstance(meal, dict) and meal.get('name'):
                    upcoming.append({
                        "date": d_str,
                        "date_obj": d_obj,
                        "day_name": d_obj.strftime("%A"),
                        "date_formatted": d_obj.strftime("%a, %b %d"),
                        "meal_type": mt,
                        "meal_title": mt.capitalize(),
                        "name": meal.get('name'),
                        "recipe_id": meal.get('recipe_id'),
                        "source": meal.get('source', 'chef'),
                        "ingredients": meal.get('ingredients', []),
                        "instructions": meal.get('instructions', []),
                        "image_url": meal.get('image_url'),
                        "completed": meal.get('completed', False),
                        "rating": meal.get('rating', 0),
                        "is_today": (d_obj == today),
                        "meal": meal
                    })
        return upcoming

    def load_config(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return data
            except Exception as e:
                print(f"DEBUG: Error loading schedule config at {self.config_file}: {e}")
        # Default fallback
        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        today_name = datetime.now().strftime("%A")
        return {
            "duration_days": 4,
            "schedule_enabled": False,
            "schedule": {d: {"breakfast": True, "lunch": True, "dinner": True} for d in days},
            "view_mode": "work_week",
            "run_day": today_name,
            "run_time": "10:00"
        }
    
    def save_config(self, config):
        with open(self.config_file, 'w') as f:
            json.dump(config, f, indent=4)

    def get_next_run_dt(self):
        """Calculates the next run datetime based on current config."""
        try:
            config = self.load_config()
            run_day = config.get('run_day', 'Sunday').strip()
            run_time = config.get('run_time', '10:00')
            
            # --- DATE PARSING LOGIC ---
            # 1. Try to parse as ISO Date (YYYY-MM-DD)
            try:
                next_run_date = datetime.strptime(run_day, "%Y-%m-%d").date()
                h, m = map(int, run_time.split(':'))
                next_run_dt = datetime.combine(next_run_date, dt_time(h, m))
                
                # If the ISO date is strictly in the past (more than 24h old), 
                # fall back to recurring logic based on that day's name.
                if next_run_dt < datetime.now() - timedelta(hours=24):
                    raise ValueError("Date is in the past")
                return next_run_dt
            except ValueError:
                # 2. Fallback to Day Name Logic
                # If run_day was an ISO date, try to get its day name
                try:
                    passed_date = datetime.strptime(run_day, "%Y-%m-%d")
                    run_day = passed_date.strftime("%A")
                except:
                    run_day = run_day.title()

                days_map = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
                if run_day not in days_map:
                    run_day = "Monday"
                    
                target_day_idx = days_map.index(run_day)
                
                now = datetime.now()
                current_day_idx = now.weekday()
                
                days_ahead = target_day_idx - current_day_idx
                if days_ahead < 0:
                    days_ahead += 7
                elif days_ahead == 0:
                    # Keep today as the run day even if the time has passed
                    # This ensures Today stays in the planning window (green) for the whole day
                    days_ahead = 0
                         
                next_run_date = now.date() + timedelta(days=days_ahead)
                h, m = map(int, run_time.split(':'))
                next_run_dt = datetime.combine(next_run_date, dt_time(h, m))
                return next_run_dt
            
            # For the purpose of the planning horizon, if today is the Run Day, we start today.
            # We only jump to next week if the target day is strictly in the past of the current week.
            # (days_ahead < 0 already handled this by adding 7)
            # This ensures that on Friday (Run Day), Friday stays green all day.
            
            return next_run_dt
        except Exception as e:
            print(f"CalendarManager Error: Failed to calculate next run: {e}")
            return None

    def get_days_for_view(self, ref_date, view_mode, next_run_dt=None, duration_override=None):
        """
        Generates a list of day objects for the requested view mode.
        Past dates (< today) sourced from history.json.
        Future dates (>= today) sourced from calendar.json.
        """
        import calendar
        
        # Ensure date object
        if isinstance(ref_date, datetime):
            ref_date = ref_date.date()
            
        today = datetime.now().date()
        year = ref_date.year
        month = ref_date.month
        
        # 1. Load Calendar (Future Source)
        calendar_events = self.load_calendar()
        
        # 2. Load History (Past Source)
        history_events = {}
        history_path = os.path.join(self.state_dir, 'history.json')
        if os.path.exists(history_path):
            try:
                with open(history_path, 'r') as f:
                    hist_data = json.load(f)
                    for entry in hist_data:
                        for m in entry.get('meals', []):
                            d = m.get('scheduled_date')
                            mt = m.get('meal_type')
                            if d and mt:
                                if d not in history_events: history_events[d] = {}
                                # Store as rich object
                                history_events[d][mt] = {
                                    "name": m.get('name'),
                                    "recipe_id": m.get('recipe_id'),
                                    "source": m.get('source'),
                                    "rating": m.get('rating')
                                }
            except Exception as e:
                print(f"Error loading history for calendar: {e}")
        
        # Determine Plan Window (Visual only)
        config = self.load_config()
        duration = duration_override if duration_override is not None else config.get('duration_days', 4)
        schedule_enabled = config.get('schedule_enabled', True)
        
        if not next_run_dt:
            next_run_dt = self.get_next_run_dt()
            
        if next_run_dt:
            start_plan = next_run_dt.date()
        else:
            start_plan = today + timedelta(days=1)
            
        if schedule_enabled and next_run_dt:
            plan_window_dates = set(
                (start_plan + timedelta(days=i)).strftime("%Y-%m-%d") 
                for i in range(duration)
            )
        else:
            plan_window_dates = set()

        cal = calendar.Calendar(firstweekday=0)
        dates_to_show = []

        if view_mode == 'month':
            dates_to_show = list(cal.itermonthdates(year, month))
        elif view_mode == 'week':
            dates_to_show = [ref_date + timedelta(days=i) for i in range(7)]
        elif view_mode == 'work_week':
            dates_to_show = [ref_date + timedelta(days=i) for i in range(5)]
        elif view_mode == '3day':
            dates_to_show = [ref_date + timedelta(days=i) for i in range(3)]
        elif view_mode == 'day':
            dates_to_show = [ref_date]
        elif view_mode == 'planning':
            # SPECIAL MODE: Show ONLY the days in the planning horizon based on START DATE
            # If start_plan is today/future, show from start_plan.
            # If we are viewing a past date, this mode behaves like 'week' unless specified.
            # But typically 'planning' implies looking at the upcoming partial horizon.
            dates_to_show = [start_plan + timedelta(days=i) for i in range(duration)]
        else:
            dates_to_show = list(cal.itermonthdates(year, month))

        calendar_days = []
        for date_obj in dates_to_show:
            date_str = date_obj.strftime("%Y-%m-%d")
            day_name = date_obj.strftime("%A")
            
            in_month = (date_obj.month == month)
            
            # SOURCE SELECTION
            if date_obj < today:
                # Past -> History
                raw_content = history_events.get(date_str, {})
            else:
                # Future/Today -> Calendar
                raw_content = calendar_events.get(date_str, {})
            
            # NORMALIZATION 
            content = {}
            for mt in ['breakfast', 'lunch', 'dinner']:
                if mt in raw_content:
                    val = raw_content[mt]
                    if isinstance(val, str):
                        content[mt] = {"name": val, "recipe_id": None, "source": "unknown"}
                    elif isinstance(val, dict):
                        content[mt] = val
            
            day_data = {
                "date_obj": date_obj,
                "date_iso": date_str,
                "date_num": date_obj.day,
                "date_str": date_str,
                "day_name": day_name,
                "is_today": (date_str == today.strftime("%Y-%m-%d")),
                "in_month": in_month,
                "in_plan_window": (date_str in plan_window_dates),
                "content": content
            }
            calendar_days.append(day_data)
            
        return calendar_days

    def get_navigation_info(self, ref_date, view_mode, duration=4):
        """
        Calculates prev_date, next_date, and formatted date_range_label
        according to the active view distance:
        1D (day) -> 1 day
        3D (3day) -> 3 days
        5D (work_week) -> 5 days
        1W (week) -> 7 days
        1M (month) -> 1 calendar month
        planning -> duration days
        """
        from datetime import date
        if isinstance(ref_date, datetime):
            ref_date = ref_date.date()
        elif isinstance(ref_date, str):
            try:
                ref_date = datetime.strptime(ref_date, "%Y-%m-%d").date()
            except:
                ref_date = datetime.now().date()
                
        today = datetime.now().date()
        year = ref_date.year
        month = ref_date.month

        if view_mode == 'day':
            prev_date = ref_date - timedelta(days=1)
            next_date = ref_date + timedelta(days=1)
            date_range_label = ref_date.strftime("%A, %b %d, %Y")
        elif view_mode == '3day':
            prev_date = ref_date - timedelta(days=3)
            next_date = ref_date + timedelta(days=3)
            end_date = ref_date + timedelta(days=2)
            date_range_label = f"{ref_date.strftime('%b %d')} – {end_date.strftime('%b %d, %Y')}"
        elif view_mode == 'work_week':
            prev_date = ref_date - timedelta(days=5)
            next_date = ref_date + timedelta(days=5)
            end_date = ref_date + timedelta(days=4)
            date_range_label = f"{ref_date.strftime('%b %d')} – {end_date.strftime('%b %d, %Y')}"
        elif view_mode == 'week':
            prev_date = ref_date - timedelta(days=7)
            next_date = ref_date + timedelta(days=7)
            end_date = ref_date + timedelta(days=6)
            date_range_label = f"{ref_date.strftime('%b %d')} – {end_date.strftime('%b %d, %Y')}"
        elif view_mode == 'month':
            if month == 1:
                prev_date = date(year - 1, 12, 1)
            else:
                prev_date = date(year, month - 1, 1)
            if month == 12:
                next_date = date(year + 1, 1, 1)
            else:
                next_date = date(year, month + 1, 1)
            date_range_label = ref_date.strftime("%B %Y")
        elif view_mode == 'planning':
            prev_date = ref_date - timedelta(days=duration)
            next_date = ref_date + timedelta(days=duration)
            end_date = ref_date + timedelta(days=max(0, duration - 1))
            date_range_label = f"{ref_date.strftime('%b %d')} – {end_date.strftime('%b %d, %Y')}"
        else:
            prev_date = ref_date - timedelta(days=7)
            next_date = ref_date + timedelta(days=7)
            date_range_label = ref_date.strftime("%B %Y")

        return {
            "prev_date": prev_date.strftime("%Y-%m-%d"),
            "next_date": next_date.strftime("%Y-%m-%d"),
            "ref_date": ref_date.strftime("%Y-%m-%d"),
            "date_range_label": date_range_label,
            "month_name": ref_date.strftime("%B"),
            "year": year,
            "today_date": today.strftime("%Y-%m-%d")
        }

    def active_plan_exists(self):
        """Checks if there are upcoming meals scheduled in calendar.json or legacy active_plan."""
        if os.path.exists(os.path.join(self.state_dir, 'active_plan.json')):
            return True
        return len(self.get_upcoming_meals(date.today(), days_ahead=30)) > 0

    def get_default_start_date(self, scheduled_run_dt=None):
        """
        Logic for default start date:
        1. If scheduled_run_dt exists and enabled -> use that date (normalized to date only)
        2. Else, find the last meal in calendar.json and use last_date + 1 day
        3. Else, use today + 1 day (Tomorrow)
        """
        config = self.load_config()
        today = datetime.now().date()
        
        # 1. Check Scheduled Run
        if scheduled_run_dt and config.get('schedule_enabled', True):
            return scheduled_run_dt.date()
            
        # 2. Check Last Meal
        calendar = self.load_calendar()
        if calendar:
            try:
                # Find the latest date string "YYYY-MM-DD"
                dates = [datetime.strptime(d, "%Y-%m-%d").date() for d in calendar.keys()]
                if dates:
                    last_date = max(dates)
                    return last_date + timedelta(days=1)
            except Exception as e:
                print(f"Error finding last meal: {e}")
                
        # 3. Fallback
        return today + timedelta(days=1)
