import os
import json
import google.genai as genai
from google.genai import types
from pydantic import BaseModel
from typing import List

class ReviewAction(BaseModel):
    action_type: str  # "SAVE_RECIPE" or "BLACKLIST" or "LEARN_PREFERENCE"
    item_name: str
    content: str # content to save (recipe text) or preference details

class ReviewResult(BaseModel):
    actions: List[ReviewAction]
    summary_message: str

class ReviewManager:
    def __init__(self, state_dir, model_manager=None):
        self.state_dir = state_dir
        self.model_manager = model_manager
        self.blacklist_file = os.path.join(state_dir, 'blacklist.json')
        # Recipes saved to user's 'recipes' folder
        self.recipes_dir = os.path.join(state_dir, 'recipes')
        os.makedirs(self.recipes_dir, exist_ok=True)

    def process_feedback(self, plan_text, feedback_text):
        """
        Analyzes user feedback on a meal plan and executes actions.
        """
        prompt = f"""
        You are an intelligent kitchen assistant manager.
        
        CONTEXT:
        The User was given this Meal Plan:
        ---
        {plan_text}
        ---
        
        The User provided this Feedback:
        "{feedback_text}"
        
        YOUR GOAL:
        Analyze the feedback and determine if you need to:
        1. **SAVE_RECIPE**: If the user loves a specific recipe, extract the FULL recipe (Ingredients + Instructions) from the plan text. Clean it up to be a standalone markdown file.
        2. **BLACKLIST**: If the user hates a recipe or ingredient, identify the specific name to ban from future plans.
        3. **LEARN_PREFERENCE**: If they mention a general preference (e.g. "Too spicy", "I love soups"), note it.
        
        Return a JSON with a list of actions.
        """
        
        print("Analyzing feedback...")
        
        try:
            model_id = self.model_manager.get_sous_chef_model_id() if self.model_manager else "gemini-2.0-flash"
            
            if self.model_manager:
                result = self.model_manager.generate(
                    model_id=model_id,
                    system_instruction=prompt,
                    user_prompt="Analyze feedback",
                    schema=ReviewResult
                )
                result = ReviewResult(**result)
            else:
                import google.genai as genai
                client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
                response = client.models.generate_content(
                    model=model_id,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=ReviewResult,
                    ),
                )
                result = response.parsed if response.parsed else ReviewResult.model_validate_json(response.text)
            messages = []
            
            for action in result.actions:
                if action.action_type == "SAVE_RECIPE":
                    self._save_recipe(action.item_name, action.content)
                    messages.append(f"Saved recipe: {action.item_name}")
                    
                elif action.action_type == "BLACKLIST":
                    self._add_to_blacklist(action.item_name)
                    messages.append(f"Blacklisted: {action.item_name}")
                    
            return f"Feedback Processed! {', '.join(messages)}"
            
        except Exception as e:
            print(f"Error processing feedback: {e}")
            return f"Error: {e}"

    def _save_recipe(self, name, content):
        """Saves a recipe as a markdown file in the PDF/Recipe folder."""
        # Sanitize filename
        safe_name = "".join([c for c in name if c.isalpha() or c.isdigit() or c==' ']).strip()
        filename = f"{safe_name}.md"
        path = os.path.join(self.recipes_dir, filename)
        
        with open(path, 'w') as f:
            f.write(content)
            
    def _add_to_blacklist(self, item):
        """Adds an item to the blacklist json."""
        if os.path.exists(self.blacklist_file):
            with open(self.blacklist_file, 'r') as f:
                data = json.load(f)
        else:
            data = []
            
        if item not in data:
            data.append(item)
            
        with open(self.blacklist_file, 'w') as f:
            json.dump(data, f, indent=4)
