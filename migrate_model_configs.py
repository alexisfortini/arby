import os
import json

def migrate_model_config(file_path):
    if not os.path.exists(file_path):
        return False
    
    try:
        with open(file_path, 'r') as f:
            config = json.load(f)
        
        changed = False
        
        # 1. Standardize Costs
        if 'costs' in config and isinstance(config['costs'], dict):
            for mid, cost_val in config['costs'].items():
                if not isinstance(cost_val, dict):
                    # Legacy float format
                    print(f"  [FIX] Converting legacy cost for {mid} in {file_path}")
                    config['costs'][mid] = {"in": str(cost_val), "out": str(cost_val)}
                    changed = True
                else:
                    # Modern format, ensure values are strings (consistent with server.py logic)
                    if not isinstance(cost_val.get('in'), str):
                        cost_val['in'] = str(cost_val.get('in', 0.0))
                        changed = True
                    if not isinstance(cost_val.get('out'), str):
                        cost_val['out'] = str(cost_val.get('out', 0.0))
                        changed = True

        # 2. Add missing defaults
        if 'custom_models' not in config:
            config['custom_models'] = []
            changed = True
        if 'hidden_ids' not in config:
            config['hidden_ids'] = []
            changed = True

        if changed:
            with open(file_path, 'w') as f:
                json.dump(config, f, indent=4)
            return True
    
    except Exception as e:
        print(f"  [ERROR] Failed to migrate {file_path}: {e}")
    
    return False

def main():
    base_dir = os.path.abspath(os.path.dirname(__file__))
    state_dir = os.path.join(base_dir, 'state')
    
    # 1. Migrate global config
    global_config = os.path.join(state_dir, 'model_config.json')
    if migrate_model_config(global_config):
        print(f"Migrated global config: {global_config}")
    
    # 2. Scan user directories
    users_dir = os.path.join(state_dir, 'users')
    if os.path.exists(users_dir):
        for user_id in os.listdir(users_dir):
            user_path = os.path.join(users_dir, user_id)
            if os.path.isdir(user_path):
                config_file = os.path.join(user_path, 'model_config.json')
                if migrate_model_config(config_file):
                    print(f"Migrated user config for {user_id}")

if __name__ == "__main__":
    main()
