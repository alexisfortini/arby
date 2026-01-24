import os
import json
import uuid
import shutil
import hashlib
import glob
import time
from typing import List, Optional
from pydantic import BaseModel
import google.genai as genai

# --- CONSTANTS ---
CATEGORIES = ["Breakfast", "Main", "Side", "Dessert", "Drink"]
PROTEINS = ["Chicken", "Pork", "Beef", "Salmon", "Tuna", "Trout", "Shrimp", "Crab", "Lobster", "Vegetarian", "Vegan"]

# --- SCHEMA ---
class Recipe(BaseModel):
    id: str
    name: str
    category: str = "Uncategorized"  # Breakfast, Main, Side, Dessert, Drink
    protein: str = "Vegetarian"      # Chicken, Pork, Beef, Salmon, Tuna, Trout, Shrimp, Crab, Lobster, Vegetarian, Vegan
    ingredients: List[str] = []
    instructions: List[str] = []
    source: str = "manual"  # 'manual', 'pdf', 'arby'
    filename: Optional[str] = None  # Filename if source is pdf
    rating: int = 0 # 0-5 stars

class CookbookManager:
    def __init__(self, base_dir, config):
        self.base_dir = base_dir
        self.state_dir = os.path.join(base_dir, 'state')
        self.cookbook_file = os.path.join(self.state_dir, 'cookbook.json')
        
        # Managed Folder Path
        # Default to iCloud if available, else local 'recipes' folder
        home = os.path.expanduser("~")
        icloud_path = os.path.join(home, "Library/Mobile Documents/com~apple~CloudDocs/Recipe Book")
        
        # Check if we should use the configured path or default
        env_path = os.environ.get("PDF_FOLDER")
        if env_path and os.path.exists(env_path):
            self.library_path = env_path
        else:
            self.library_path = config.get('cookbook_dir', icloud_path)
        
        # Gemeni Client for Parsing
        self.api_key = os.environ.get("GEMINI_API_KEY")
        self.client = genai.Client(api_key=self.api_key) if self.api_key else None
        
        # Blacklist for ignored PDFs
        self.blacklist_file = os.path.join(self.state_dir, 'blacklist.json')

        # Normalization
        self._normalize_categories()

    def _clean_title(self, title: str) -> str:
        """Cleans up recipe titles: removes fluff, fixes casing."""
        if not title: return "Untitled Recipe"
        
        # 1. Fix ALL CAPS
        if title.isupper():
            title = title.title()
            
        # 2. Remove Fluff Words (Case Insensitive Regex)
        fluff_patterns = [
            r'\b(?:The )?Best\s+Ever\b',
            r'\b(?:The )?Best\b',
            r'\bAmazing\b',
            r'\bDelicious\b',
            r'\bHealthy\b',
            r'\bEasy\b',
            r'\bSimple\b',
            r'\bPerfect\b',
            r'\bWorld\'s Best\b',
            r'\bAuthentic\b',
            r'\bQuick\b',
            r'\d+\s*-?\s*(?:min|minute|hr|hour)s?\b', # "20 Min", "30 Minute"
        ]
        
        cleaned = title
        import re
        for pattern in fluff_patterns:
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
            
        # 3. Clean up extra spaces/punctuation
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        cleaned = re.sub(r'^\W+|\W+$', '', cleaned) # Trim leading/trailing non-word chars
        
        # If we stripped everything (e.g. just "Best Ever"), revert to original but Title Case
        if not cleaned:
            return title.title()
            
        return cleaned

    def _normalize_categories(self):
        """Fix categories and clean up titles."""
        recipes = self.load_recipes()
        changed = False
        allowed_categories = set(CATEGORIES)
        
        for r in recipes:
            # 1. Categories
            cat = r.get('category', 'Uncategorized')
            
            # Mappings
            if cat in ["Main Course", "Main Dish", "Dinner", "Lunch", "Soup", "Stew", "Pasta", "Pizza", "Salad", "Sandwich"]:
                r['category'] = "Main"
                changed = True
            elif cat in ["Beverage", "Cocktail", "Smoothie"]:
                r['category'] = "Drink"
                changed = True
            elif cat in ["Appetizer", "Starter", "Snack"]:
                r['category'] = "Side"
                changed = True
            elif cat in ["Cake", "Cookie", "Pie", "Sweet"]:
                r['category'] = "Dessert"
                changed = True
            
            # Strict Enforcement: If still not in list, force to Main
            if r['category'] not in allowed_categories:
                 print(f"DEBUG: Coercing invalid category '{r['category']}' to 'Main'")
                 r['category'] = "Main"
                 changed = True
            
            # 2. Backfill Protein
            if 'protein' not in r:
                r['protein'] = "Vegetarian"
                changed = True

            # 3. Clean Title
            original_name = r.get('name', '')
            clean_name = self._clean_title(original_name)
            if clean_name != original_name:
                r['name'] = clean_name
                print(f"DEBUG: Renamed '{original_name}' -> '{clean_name}'")
                changed = True
        
        if changed:
            print("DEBUG: Normalized recipe data (Categories & Titles).")
            self.save_recipes(recipes)

    def load_blacklist(self) -> List[str]:
        if not os.path.exists(self.blacklist_file):
            return []
        try:
            with open(self.blacklist_file, 'r') as f:
                return json.load(f)
        except:
            return []

    def save_blacklist(self, blacklist: List[str]):
        with open(self.blacklist_file, 'w') as f:
            json.dump(blacklist, f, indent=4)
            
    def restore_ignored_file(self, filename):
        blacklist = self.load_blacklist()
        if filename in blacklist:
            blacklist.remove(filename)
            self.save_blacklist(blacklist)
            return True
        return False

    def load_recipes(self) -> List[dict]:
        if not os.path.exists(self.cookbook_file):
            return []
        try:
            with open(self.cookbook_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            validated = []
            for r in data:
                try:
                    # Ensure ID exists for validation
                    if 'id' not in r: r['id'] = str(uuid.uuid4())
                    validated.append(Recipe(**r).model_dump())
                except Exception as e:
                    print(f"Skipping malformed recipe: {e}")
            return validated
        except Exception as e:
            print(f"Error loading cookbook: {e}")
            return []

    def save_recipes(self, recipes: List[dict]):
        with open(self.cookbook_file, 'w') as f:
            json.dump(recipes, f, indent=4)

    def get_recipe(self, recipe_id):
        recipes = self.load_recipes()
        return next((r for r in recipes if r['id'] == recipe_id), None)

    def add_recipe(self, recipe_data: dict) -> Recipe:
        recipes = self.load_recipes()
        
        # Ensure ID
        if 'id' not in recipe_data:
            recipe_data['id'] = str(uuid.uuid4())
            
        # Validate with Schema (will raise if invalid)
        recipe = Recipe(**recipe_data)
        
        recipes.append(recipe.model_dump())
        self.save_recipes(recipes)
        return recipe

    def update_recipe(self, recipe_id, updates: dict):
        recipes = self.load_recipes()
        for i, r in enumerate(recipes):
            if r['id'] == recipe_id:
                # Merge updates
                recipes[i].update(updates)
                self.save_recipes(recipes)
                return recipes[i]
        return None

    def rate_recipe(self, recipe_id, rating: int):
        recipes = self.load_recipes()
        for i, r in enumerate(recipes):
            if r['id'] == recipe_id:
                recipes[i]['rating'] = rating
                self.save_recipes(recipes)
                print(f"DEBUG: Rated recipe {recipe_id} with {rating} stars.")
                return True
        return False

    def delete_recipe(self, recipe_id):
        recipes = self.load_recipes()
        target = next((r for r in recipes if r['id'] == recipe_id), None)
        
        if target:
            # If it's a PDF, add to blacklist so we don't re-import it
            if target.get('source') == 'pdf' and target.get('filename'):
                blacklist = self.load_blacklist()
                if target['filename'] not in blacklist:
                    blacklist.append(target['filename'])
                    self.save_blacklist(blacklist)
                print(f"Added {target['filename']} to ignore list.")
            
            recipes = [r for r in recipes if r['id'] != recipe_id]
            self.save_recipes(recipes)
            return True
        return False

    def batch_delete_recipes(self, recipe_ids: List[str]):
        """Deletes multiple recipes by ID, handling blacklisting for PDFs."""
        recipes = self.load_recipes()
        blacklist = self.load_blacklist()
        blacklist_changed = False
        
        # Identify targets
        targets = [r for r in recipes if r['id'] in recipe_ids]
        
        for target in targets:
             # Handle PDF Blacklist
             if target.get('source') == 'pdf' and target.get('filename'):
                if target['filename'] not in blacklist:
                    blacklist.append(target['filename'])
                    blacklist_changed = True
                    print(f"Added {target['filename']} to ignore list (Batch Delete).")
        
        if blacklist_changed:
            self.save_blacklist(blacklist)
            
        # Filter out deleted
        new_recipes = [r for r in recipes if r['id'] not in recipe_ids]
        
        if len(new_recipes) != len(recipes):
            self.save_recipes(new_recipes)
            return True
        return False

    def batch_update_recipes(self, recipe_ids: List[str], updates: dict):
        """Updates multiple recipes with the same changes (e.g. category/protein)."""
        recipes = self.load_recipes()
        changed = False
        
        for r in recipes:
            if r['id'] in recipe_ids:
                r.update(updates)
                changed = True
                
        if changed:
            self.save_recipes(recipes)
            return True
        return False

    # --- MIGRATION & SYNC ---

    def initialize(self, legacy_pdf_folder=None):
        """Creates managed folder and migrates legacy files if needed."""
        # Only create if it looks like a local managed path (not iCloud root)
        # But for iCloud, we might not want to mkdir if they have it set up.
        # Safe to try:
        if not os.path.exists(self.library_path):
             try:
                 os.makedirs(self.library_path, exist_ok=True)
                 print(f"Created Cookbook Library at: {self.library_path}")
             except:
                 pass
            
        # Migration: If library is empty but we have a legacy folder
        if legacy_pdf_folder and os.path.exists(legacy_pdf_folder) and legacy_pdf_folder != self.library_path:
            existing_files = os.listdir(self.library_path)
            if not existing_files:
                print("Migrating PDFs from Legacy folder...")
                for file in os.listdir(legacy_pdf_folder):
                    if file.lower().endswith('.pdf'):
                        src = os.path.join(legacy_pdf_folder, file)
                        dst = os.path.join(self.library_path, file)
                        shutil.copy2(src, dst)
                print("Migration complete.")

    def sync_library(self, progress_callback=None, model_id="gemini-1.5-flash", model_manager=None, cancel_check=None):
        """Scans folder, adds new PDFs, removes missing ones.
           progress_callback: func(current, total, status_msg)
           model_id: Model to use for extraction
           model_manager: Agent's ModelManager instance (for non-Gemini models)
           cancel_check: func() -> bool. If true, abort sync.
        """
        if not self.client:
            print(f"DEBUG: No API Key found in CookbookManager. Keys: {self.api_key[:5] if self.api_key else 'None'}")
            print("No API Key, skipping AI sync.")
            if progress_callback: progress_callback(0, 0, "Error: No API Key found.")
            return

        print(f"Syncing Library from: {self.library_path}")
        if not os.path.exists(self.library_path):
            print(f"CRITICAL: Library path does not exist: {self.library_path}")
            if progress_callback: progress_callback(0, 0, f"Error: Path not found: {self.library_path}")
            return
        
        recipes = self.load_recipes()
        blacklist = self.load_blacklist()
        
        # 1. Get current files
        # Recursive os.walk
        pdf_files = []
        for root, dirs, files in os.walk(self.library_path):
            for file in files:
                if file.lower().endswith('.pdf'):
                    pdf_files.append(os.path.join(root, file))
                
        filenames = {os.path.basename(f) for f in pdf_files}
        total_files = len(pdf_files)
        print(f"Found {total_files} PDF files in library.")
        
        if progress_callback:
            progress_callback(0, total_files, f"Found {total_files} PDFs. Checking for new recipes...")
        
        # 2. Prune recipes pointing to missing files
        # (Optional: remove recipes whose PDFs are gone? Or keep them manual?)
        # Current logic: We only add, we don't auto-delete unless explicit.
        
        known_filenames = {r.get('filename') for r in recipes if r.get('filename')}

        # 3. Ingest new files
        count = 0
        added_names = []
        
        for i, file_path in enumerate(pdf_files):
            # Check Cancellation
            if cancel_check and cancel_check():
                print("DEBUG: Sync Cancelled by User.")
                if progress_callback: progress_callback(count, total_files, "Cancelled.")
                return added_names

            count += 1
            fname = os.path.basename(file_path)
            
            # Skip if blacklisted
            if fname in blacklist:
                print(f"Skipping ignored file: {fname}")
                if progress_callback:
                    progress_callback(count, total_files, f"Skipping ignored: {fname}")
                continue
                
            if fname not in known_filenames:
                print(f"New PDF found: {fname}. Extracting data...")
                if progress_callback:
                    progress_callback(count, total_files, f"Parsing with AI: {fname}")
                
                # RETRY LOOP FOR RATE LIMITS
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        extracted = self._extract_recipe_from_pdf(file_path, model_id, model_manager)
                        if extracted:
                            extracted['filename'] = fname
                            extracted['source'] = 'pdf'
                            extracted['id'] = str(uuid.uuid4())
                            recipes.append(extracted)
                            
                            # SAVE IMMEDIATELY
                            self.save_recipes(recipes)
                            
                            recipe_name = extracted['name']
                            added_names.append(recipe_name)
                            print(f"DEBUG: Saved recipe '{recipe_name}' from {fname}")
                            if progress_callback:
                                progress_callback(count, total_files, f"Added: {recipe_name}")
                            
                            
                        # Success? Break.
                        # Also add a small delay to be nice to the API
                        time.sleep(2) 
                        break
                        
                    except Exception as e:
                        # Check for 429
                        error_str = str(e)
                        if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                            wait_time = 60
                            print(f"Rate Limit Hit. Sleeping {wait_time}s...")
                            if progress_callback:
                                progress_callback(count, total_files, f"Rate Limit (Quota). Pausing {wait_time}s...")
                            time.sleep(wait_time)
                            # Retry
                            continue
                        else:
                            # Other error? Log and Skip.
                            print(f"Failed to parse {fname}: {e}")
                            break
            else:
                 # Already exists
                 if progress_callback:
                    progress_callback(count, total_files, f"Skipping existing: {fname}")
        
        self.save_recipes(recipes)
        print("Sync Complete.")
        return added_names

    def _extract_recipe_from_pdf(self, file_path, model_id="gemini-1.5-flash", model_manager=None):
        """Uses Gemini to parse PDF into structured Recipe."""
        # Note: Exceptions are handled by caller to support rate-limit retries

        # FAILSAFE: This method uses google.genai SDK which only works with Gemini models
        # If the user selected GPT-4o/Claude as Sous Chef, we must fallback to a Gemini model
        # provided we have the key.
        if not model_id.startswith("gemini"):
            print(f"DEBUG: Requested non-Gemini model '{model_id}' for PDF Sync. Falling back to gemini-1.5-flash.")
            model_id = "gemini-1.5-flash"
        
        # Upload file using path string (SDK auto-detects mime_type from extension)
        uploaded_file = self.client.files.upload(file=file_path)
        
        prompt = """
        Extract the recipe from this PDF into JSON format.
        
        STRICT TITLE RULES:
        1. Extract the name as a clean, concise title.
        2. Remove subjective adjectives like "Best Ever", "Amazing", "Delicious", "Healthy", "Perfect". 
        3. Remove duration indicators like "20 Minute", "30 Min".
        4. Use Title Case. Do NEVER use ALL CAPS.
        
        STRICT CATEGORIZATION RULES:
        1. "category": Must be one of ["Breakfast", "Main", "Side", "Dessert", "Drink"]. 
           - "Main" applies to Lunch or Dinner.
        2. "protein": Must be one of ["Chicken", "Pork", "Beef", "Salmon", "Tuna", "Trout", "Shrimp", "Crab", "Lobster", "Vegetarian", "Vegan"].
           - If multiple meats, pick the dominant one.
           - If no meat, use "Vegetarian" or "Vegan".
        
        Structure:
        {
            "name": "Recipe Title",
            "category": "Main",
            "protein": "Chicken",
            "ingredients": ["1 cup flour", ...],
            "instructions": ["Step 1...", "Step 2..."]
        }
        Only return the JSON.
        """
        
        response = self.client.models.generate_content(
            model=model_id,
            contents=[uploaded_file, prompt],
            config={
                'response_mime_type': 'application/json',
                'response_schema': Recipe
            }
        )
        
        if response.parsed:
            return response.parsed.model_dump()
        return None


        

