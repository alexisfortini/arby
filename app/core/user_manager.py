import os
import json
import uuid
import shutil
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin

class User(UserMixin):
    def __init__(self, id, name, email, password_hash):
        self.id = id
        self.name = name
        self.email = email
        self.password_hash = password_hash
        
    @staticmethod
    def from_dict(data):
        return User(
            id=data['id'],
            name=data['name'],
            email=data['email'],
            password_hash=data['password_hash']
        )
        
    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "password_hash": self.password_hash
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
