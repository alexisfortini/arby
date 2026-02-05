import os
import json
from datetime import datetime, timedelta, time as dt_time

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
        return {
            "duration_days": 4,
            "schedule_enabled": True,
            "schedule": {d: {"breakfast": True, "lunch": True, "dinner": True} for d in days},
            "view_mode": "work_week",
            "run_day": "Sunday",
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
                    # If it's today, check if the time has already passed
                    h, m = map(int, run_time.split(':'))
                    if now.time() > dt_time(h, m):
                         days_ahead = 7
                         
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

    def get_days_for_view(self, ref_date, view_mode, next_run_dt=None):
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
        duration = config.get('duration_days', 8)
        
        if config.get('schedule_enabled', True):
            if not next_run_dt:
                next_run_dt = self.get_next_run_dt()
                
            if next_run_dt:
                start_plan = next_run_dt.date()
            else:
                start_plan = today + timedelta(days=1)
                
            plan_window_dates = set(
                (start_plan + timedelta(days=i)).strftime("%Y-%m-%d") 
                for i in range(duration)
            )
        else:
            plan_window_dates = set()

        cal = calendar.Calendar(firstweekday=0)
        dates_to_show = []

        if view_mode == 'month':
            dates_to_show = [ref_date + timedelta(days=i) for i in range(30)]
        elif view_mode == 'week':
            dates_to_show = [ref_date + timedelta(days=i) for i in range(7)]
        elif view_mode == 'work_week':
            dates_to_show = [ref_date + timedelta(days=i) for i in range(5)]
        elif view_mode == '3day':
            dates_to_show = [ref_date + timedelta(days=i) for i in range(3)]
        elif view_mode == 'day':
            dates_to_show = [ref_date]
        else:
            dates_to_show = [ref_date + timedelta(days=i) for i in range(30)]

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

    def active_plan_exists(self):
        """Checks if there is an active plan file."""
        return os.path.exists(os.path.join(self.state_dir, 'active_plan.json'))

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
