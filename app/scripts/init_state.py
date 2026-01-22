import os
import json

def init_state():
    state_dir = "state"
    if not os.path.exists(state_dir):
        os.makedirs(state_dir)
        print(f"Created {state_dir}/")

    files = {
        "active_plan.json": {},
        "blacklist.json": [],
        "calendar.json": {},
        "cookbook.json": [],
        "current_draft.json": {},
        "file_hashes.json": {},
        "history.json": [],
        "ideas.txt": "",
        "inventory.json": [],
        "model_config.json": {"custom_models": [], "hidden_ids": [], "core_model": "gemini-2.5-flash"},
        "preferences.json": {},
        "schedule_config.json": {}
    }

    for filename, default_content in files.items():
        filepath = os.path.join(state_dir, filename)
        if not os.path.exists(filepath):
            with open(filepath, 'w') as f:
                if isinstance(default_content, (dict, list)):
                    json.dump(default_content, f, indent=4)
                else:
                    f.write(default_content)
            print(f"Created default {filename}")
        else:
            print(f"Skipped {filename} (already exists)")

if __name__ == "__main__":
    init_state()
