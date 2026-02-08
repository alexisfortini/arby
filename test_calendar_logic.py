import os
import json
from datetime import datetime, date, timedelta, time as dt_time
import sys

# Add app to path
sys.path.append(os.getcwd())

from app.core.calendar_manager import CalendarManager

def test_overrides():
    mgr = CalendarManager(os.getcwd())
    
    # CASE 1: Default
    print("--- CASE 1: Default ---")
    days = mgr.get_days_for_view(date.today(), 'planning')
    print(f"Num days: {len(days)}")
    print(f"Start date: {days[0]['date_iso']}")
    
    # CASE 2: Duration override
    print("\n--- CASE 2: Duration override (6) ---")
    days = mgr.get_days_for_view(date.today(), 'planning', duration_override=6)
    print(f"Num days: {len(days)}")
    
    # CASE 3: Start date override (via next_run_dt)
    print("\n--- CASE 3: Start date override (Today + 5 days) ---")
    target_date = date.today() + timedelta(days=5)
    mock_run = datetime.combine(target_date, dt_time(10, 0))
    days = mgr.get_days_for_view(target_date, 'planning', next_run_dt=mock_run)
    print(f"Start date: {days[0]['date_iso']}")
    print(f"In Plan Window: {days[0]['in_plan_window']}")

if __name__ == "__main__":
    test_overrides()
