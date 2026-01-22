import os
import json
from datetime import datetime, timedelta

class CalendarManager:
    def __init__(self, base_dir):
        self.base_dir = base_dir
        self.calendar_file = os.path.join(base_dir, 'state/calendar.json')
        self.config_file = os.path.join(base_dir, 'state/schedule_config.json')

    def load_calendar(self):
        if os.path.exists(self.calendar_file):
            with open(self.calendar_file, 'r') as f:
                return json.load(f)
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
            with open(self.config_file, 'r') as f:
                return json.load(f)
        # Default fallback
        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        return {
            "duration_days": 8,
            "schedule_enabled": True,
            "schedule": {d: {"breakfast": True, "lunch": True, "dinner": True} for d in days},
            "view_mode": "work_week"
        }
    
    def save_config(self, config):
        with open(self.config_file, 'w') as f:
            json.dump(config, f, indent=4)

    def get_days_for_view(self, ref_date, view_mode):
        """
        Generates a list of day objects for the requested view mode.
        ref_date: datetime.date or datetime.datetime
        view_mode: str ('month', 'week', 'work_week', '3day', 'day')
        """
        import calendar
        
        # Ensure date object
        if isinstance(ref_date, datetime):
            ref_date = ref_date.date()
            
        today = datetime.now().date()
        year = ref_date.year
        month = ref_date.month
        
        # Load events
        events = self.load_calendar()
        
        # Determine Plan Window (Visual only, based on today)
        config = self.load_config()
        duration = config.get('duration_days', 7)
        start_plan = today + timedelta(days=1)
        plan_window_dates = [ (start_plan + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(duration) ]

        cal = calendar.Calendar(firstweekday=0) # 0 = Monday
        dates_to_show = []

        if view_mode == 'month':
            dates_to_show = list(cal.itermonthdates(year, month))
        elif view_mode == 'week':
            # Normalize to Monday
            start_of_week = ref_date - timedelta(days=ref_date.weekday())
            dates_to_show = [start_of_week + timedelta(days=i) for i in range(7)]
        elif view_mode == 'work_week':
            # Normalize to Monday
            start_of_week = ref_date - timedelta(days=ref_date.weekday())
            dates_to_show = [start_of_week + timedelta(days=i) for i in range(5)]
        elif view_mode == '3day':
            dates_to_show = [ref_date + timedelta(days=i) for i in range(3)]
        elif view_mode == 'day':
            dates_to_show = [ref_date]
        else:
            dates_to_show = list(cal.itermonthdates(year, month))

        calendar_days = []
        for date_obj in dates_to_show:
            date_str = date_obj.strftime("%Y-%m-%d")
            day_name = date_obj.strftime("%A")
            
            # Month View styling constraint
            in_month = (date_obj.month == month)
            
            content = events.get(date_str, {})
            
            day_data = {
                "date_obj": date_obj,
                "date_iso": date_str, # Helper for JS
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
