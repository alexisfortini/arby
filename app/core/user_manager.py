import os
import json
import uuid
import shutil
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin

class User(UserMixin):
    def __init__(self, id, name, email, password_hash, storage_limit_mb=100):
        self.id = id
        self.name = name
        self.email = email
        self.password_hash = password_hash
        self.storage_limit_mb = storage_limit_mb
        
    @staticmethod
    def from_dict(data):
        return User(
            id=data['id'],
            name=data['name'],
            email=data['email'],
            password_hash=data['password_hash'],
            storage_limit_mb=data.get('storage_limit_mb', 100)
        )
        
    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "password_hash": self.password_hash,
            "storage_limit_mb": self.storage_limit_mb
        }

class UserManager:
    def __init__(self, base_dir):
        self.base_dir = base_dir
        self.state_dir = os.path.join(base_dir, 'state')
        self.users_file = os.path.join(self.state_dir, 'users.json')
        self.users_dir = os.path.join(self.state_dir, 'users')
        
        self._ensure_setup()
        
    def _ensure_setup(self):
        if not os.path.exists(self.users_dir):
            os.makedirs(self.users_dir)
            
        if not os.path.exists(self.users_file):
            with open(self.users_file, 'w') as f:
                json.dump([], f)
                
    def load_users(self):
        try:
            with open(self.users_file, 'r') as f:
                data = json.load(f)
                return [User.from_dict(u) for u in data]
        except:
            return []
            
    def save_users(self, users):
        with open(self.users_file, 'w') as f:
            json.dump([u.to_dict() for u in users], f, indent=4)
            
    def get_user(self, user_id):
        users = self.load_users()
        for u in users:
            if u.id == user_id:
                return u
        return None
        
    def get_user_by_email(self, email):
        users = self.load_users()
        for u in users:
            if u.email.lower() == email.lower():
                return u
        return None
        
    def create_user(self, name, email, password):
        if self.get_user_by_email(email):
             return None, "Email already exists"
             
        user_id = str(uuid.uuid4())
        pw_hash = generate_password_hash(password)
        
        new_user = User(
            id=user_id,
            name=name,
            email=email,
            password_hash=pw_hash
        )
        
        users = self.load_users()
        users.append(new_user)
        self.save_users(users)
        
        # Create User Directory
        user_path = os.path.join(self.users_dir, user_id)
        os.makedirs(user_path, exist_ok=True)
        
        return new_user, None
        
    def verify_login(self, email, password):
        user = self.get_user_by_email(email)
        if user and check_password_hash(user.password_hash, password):
            return user
        return None

    def update_user(self, user_id, name=None, email=None, password=None):
        users = self.load_users()
        user_idx = next((i for i, u in enumerate(users) if u.id == user_id), -1)
        
        if user_idx == -1:
            return None, "User not found"
            
        user = users[user_idx]
        
        if name:
            user.name = name
        if email:
            # Check for email conflict
            existing = self.get_user_by_email(email)
            if existing and existing.id != user_id:
                return None, "Email already in use"
            user.email = email
        if password:
            user.password_hash = generate_password_hash(password)
            
        users[user_idx] = user
        self.save_users(users)
        return user, None

    def delete_user(self, user_id):
        users = self.load_users()
        users = [u for u in users if u.id != user_id]
        self.save_users(users)
        
        # Delete User Directory
        user_path = os.path.join(self.users_dir, user_id)
        if os.path.exists(user_path):
            shutil.rmtree(user_path)
            
        return True

    def get_user_storage_usage(self, user_id):
        user_path = os.path.join(self.users_dir, user_id)
        if not os.path.exists(user_path):
            return 0
        total_size = 0
        for dirpath, dirnames, filenames in os.walk(user_path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                try:
                    total_size += os.path.getsize(fp)
                except OSError:
                    pass
        return total_size / (1024 * 1024) # MB

    def wipe_user_data(self, user_id):
        user_path = os.path.join(self.users_dir, user_id)
        if not os.path.exists(user_path):
            return False, "User data directory not found"
        
        # Keep essential config, wipe everything else
        files_to_preserve = ['preferences.json', 'model_config.json']
        
        for item in os.listdir(user_path):
            item_path = os.path.join(user_path, item)
            if item in files_to_preserve:
                continue
            try:
                if os.path.isfile(item_path) or os.path.islink(item_path):
                    os.unlink(item_path)
                elif os.path.isdir(item_path):
                    shutil.rmtree(item_path)
            except Exception as e:
                print(f"Error wiping {item_path}: {e}")
        
        return True, None

    def set_user_storage_limit(self, user_id, limit_mb):
        users = self.load_users()
        for u in users:
            if u.id == user_id:
                u.storage_limit_mb = int(limit_mb)
                self.save_users(users)
                return True
        return False
