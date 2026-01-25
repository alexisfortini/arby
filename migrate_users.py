import os
import shutil
import sys
from app.core.user_manager import UserManager

def migrate():
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__)))
    state_dir = os.path.join(base_dir, 'state')
    
    # Initialize User Object
    user_manager = UserManager(base_dir)
    
    # Check if we already have users
    if user_manager.load_users():
        print("Users already exist. Skipping migration to prevent overwriting.")
        return

    print("Starting Migration to Multi-User Architecture...")
    
    # 1. Create Default User
    name = "Alexis Fortini"
    email = "axs.fortini@gmail.com"
    password = "admin" # Temporary password, user should change it
    
    print(f"Creating default user: {name} ({email})")
    user, error = user_manager.create_user(name, email, password)
    
    if error:
        print(f"Error creating user: {error}")
        return
        
    user_id = user.id
    user_state_dir = os.path.join(state_dir, f'users/{user_id}')
    
    print(f"User created. ID: {user_id}")
    print(f"Migrating data to: {user_state_dir}")
    
    # 2. Move Files
    files_to_move = [
        'calendar.json',
        'inventory.json',
        'cookbook.json',
        'history.json',
        'preferences.json',
        'ideas.txt',
        'schedule_config.json',
        'active_plan.json',
        'blacklist.json',
        'current_draft.json' 
    ]
    
    count = 0
    for filename in files_to_move:
        src = os.path.join(state_dir, filename)
        dst = os.path.join(user_state_dir, filename)
        
        if os.path.exists(src):
            try:
                shutil.move(src, dst)
                print(f"  [MOVED] {filename}")
                count += 1
            except Exception as e:
                print(f"  [ERROR] Failed to move {filename}: {e}")
        else:
            print(f"  [SKIP] {filename} (not found)")
            
    # 3. Create 'recipes' folder if needed?
    # CookbookManager handles that on init usually.
    
    print(f"Migration Complete. Moved {count} files.")
    print(f"Login with: {email} / {password}")

if __name__ == "__main__":
    migrate()
