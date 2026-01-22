import json
import os
import time
from datetime import datetime
import google.genai as genai
from google.genai import types

from pydantic import BaseModel

class Ingredient(BaseModel):
    item: str
    brand: str | None = None
    quantity: float
    unit: str
    size_value: float | None = None
    size_unit: str | None = None
    purchase_date: str | None = None
    expiry_date: str | None = None
    expiry_estimate_days: int | None = None

class IngredientList(BaseModel):
    ingredients: list[Ingredient]

class ItemToRemoval(BaseModel):
    has_match: bool
    inventory_index: int | None = None
    reason: str | None = None

class MatchResult(BaseModel):
    has_match: bool
    inventory_index: int | None = None

class InventoryManager:
    def __init__(self, inventory_file, model_manager=None):
        self.inventory_file = inventory_file
        self.model_manager = model_manager

    def load_inventory(self):
        if os.path.exists(self.inventory_file):
            with open(self.inventory_file, 'r') as f:
                return json.load(f)
        return []

    def save_inventory(self, items):
        with open(self.inventory_file, 'w') as f:
            json.dump(items, f, indent=4)

    def delete_item(self, index):
        inventory = self.load_inventory()
        if 0 <= index < len(inventory):
            del inventory[index]
            self.save_inventory(inventory)
            return True
        return False

    def update_item(self, index, data):
        inventory = self.load_inventory()
        if 0 <= index < len(inventory):
            # Preserve fields not in data if needed, or strictly overwrite? 
            # We'll merge data into existing
            inventory[index].update(data)
            self.save_inventory(inventory)
            return True
        return False

    def _title_case(self, s):
        if not s:
            return s
        return " ".join([word.capitalize() for word in s.split()])

    def parse_and_add(self, natural_language_input):
        """Uses Gemini to parse natural language ingredients into structured JSON."""
        
        prompt = f"""
        Extract the ingredients from this text: "{natural_language_input}"
        
        Rules:
        1. Always capitalize the first letter of each word in 'item' and 'brand' (e.g., "Olive Oil", "Katz Farms").
        2. Use standardized lowercase units (oz, lb, kg, L, ml, ct).
        3. Estimate quantity if missing (e.g., "bag of rice" -> 1 kg, "milk" -> 1 gallon/3.7 liters).
        4. Estimate 'expiry_estimate_days' based on the type of food (e.g., milk=7, rice=365, vegetables=5).
        5. If brand is mentioned, extract it.
        """

        try:
            # Resolve Model ID (Sous Chef)
            model_id = self.model_manager.get_sous_chef_model_id() if self.model_manager else "gemini-2.0-flash"
            
            # Use ModelManager for generation
            if self.model_manager:
                result = self.model_manager.generate(
                    model_id=model_id,
                    system_instruction=prompt,
                    user_prompt=f"Parse these items: {natural_language_input}",
                    schema=IngredientList
                )
                new_items = result.get('ingredients', [])
            else:
                # Fallback if no model manager (dev/test)
                response = self.client.models.generate_content(
                    model=model_id,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=IngredientList,
                    ),
                )
                if response.parsed:
                    new_items = response.parsed.ingredients
                else:
                    new_items = IngredientList.model_validate_json(response.text).ingredients
            
            inventory = self.load_inventory()
            
            for item in new_items:
                item_name = self._title_case(item.item)
                brand_name = self._title_case(item.brand)

                # Find Match in current inventory
                match_found = False
                # Simple name + unit match for efficiency during bulk add, 
                # or we can use the same LLM logic but LLM for each item in a loop might be slow.
                # Let's use a simpler heuristic for bulk, or just iterate and use the LLM if we want to be "Arby-smart".
                
                # Given we want to be smart:
                for existing in inventory:
                    if existing['item'].lower() == item_name.lower() and existing['unit'].lower() == item.unit.lower():
                        existing['quantity'] += item.quantity
                        existing['updated_on'] = datetime.now().strftime("%Y-%m-%d")
                        match_found = True
                        break
                
                if not match_found:
                    entry = {
                        "item": item_name,
                        "brand": brand_name,
                        "quantity": item.quantity,
                        "unit": item.unit.lower() if item.unit else "ct",
                        "size_value": item.size_value,
                        "size_unit": item.size_unit.lower() if item.size_unit else None,
                        "purchase_date": datetime.now().strftime("%Y-%m-%d"),
                        "expiry_date": item.expiry_date,
                        "expiry_estimate_days": item.expiry_estimate_days,
                        "added_on": datetime.now().strftime("%Y-%m-%d")
                    }
                    inventory.append(entry)
                
            self.save_inventory(inventory)
            return len(new_items)
        except Exception as e:
            print(f"Error parsing ingredients: {e}")
            return 0

    def add_one_smartly(self, ingredient_str):
        """Parses a single ingredient string and either updates existing or adds new."""
        # 1. Parse it
        prompt = f"""
        Extract the ingredient from this text: "{ingredient_str}"
        Rules:
        1. Always capitalize the first letter of each word in 'item' and 'brand'.
        2. Use standardized lowercase units (oz, lb, kg, L, ml, ct).
        3. Estimate 'expiry_estimate_days'.
        """
        
        try:
            model_id = self.model_manager.get_sous_chef_model_id() if self.model_manager else "gemini-2.0-flash"
            
            if self.model_manager:
                result = self.model_manager.generate(
                    model_id=model_id,
                    system_instruction=prompt,
                    user_prompt=f"Parse: {ingredient_str}",
                    schema=IngredientList
                )
                parsed = IngredientList(**result)
            else:
                response = self.client.models.generate_content(
                    model=model_id,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=IngredientList,
                    ),
                )
                parsed = response.parsed if response.parsed else IngredientList.model_validate_json(response.text)
            
            if not parsed.ingredients:
                return False, "Could not parse ingredient."
            
            new_item = parsed.ingredients[0]
            new_item.item = self._title_case(new_item.item)
            new_item.brand = self._title_case(new_item.brand)
            
            inventory = self.load_inventory()
            
            # 2. Find Match
            match_prompt = f"""
            We are adding this item: "{new_item.item} ({new_item.brand or 'No Brand'})"
            Does this match any item already in the pantry?
            
            Inventory:
            {self.get_summary()}
            
            Rules:
            1. Only return has_match=true if it's clearly the same ingredient (e.g. 'Onion' and 'Yellow Onion' is a match).
            2. If brand is different but item is common, it's still a match (e.g. 'Whole Milk' vs 'Milk').
            """
            
            if self.model_manager:
                result = self.model_manager.generate(
                    model_id=model_id,
                    system_instruction=match_prompt,
                    user_prompt="Analyze",
                    schema=MatchResult
                )
                match_result = MatchResult(**result)
            else:
                match_response = self.client.models.generate_content(
                    model=model_id,
                    contents=match_prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=MatchResult,
                    ),
                )
                match_result = match_response.parsed if match_response.parsed else MatchResult.model_validate_json(match_response.text)
            
            if match_result.has_match and match_result.inventory_index is not None:
                idx = match_result.inventory_index
                if 0 <= idx < len(inventory):
                    existing = inventory[idx]
                    # Update quantity if units match, otherwise overwrite
                    if existing['unit'].lower() == new_item.unit.lower():
                        existing['quantity'] += new_item.quantity
                    else:
                        existing['quantity'] = new_item.quantity
                        existing['unit'] = new_item.unit.lower()
                    
                    existing['updated_on'] = datetime.now().strftime("%Y-%m-%d")
                    self.save_inventory(inventory)
                    return True, f"Updated {existing['item']} in pantry."
            
            # 3. Add as new
            entry = {
                "item": new_item.item,
                "brand": new_item.brand,
                "quantity": new_item.quantity,
                "unit": new_item.unit.lower() if new_item.unit else "ct",
                "size_value": new_item.size_value,
                "size_unit": new_item.size_unit.lower() if new_item.size_unit else None,
                "purchase_date": datetime.now().strftime("%Y-%m-%d"),
                "expiry_date": new_item.expiry_date,
                "expiry_estimate_days": new_item.expiry_estimate_days,
                "added_on": datetime.now().strftime("%Y-%m-%d")
            }
            inventory.append(entry)
            self.save_inventory(inventory)
            return True, f"Added {new_item.item} to pantry."

        except Exception as e:
            print(f"Error in add_one_smartly: {e}")
            return False, str(e)

    def get_summary(self):
        inventory = self.load_inventory()
        if not inventory:
            return "Pantry is empty."
        return ", ".join([f"[{idx}] {i['quantity']} {i['unit']} of {i['item']} ({i.get('brand', 'No Brand')})" for idx, i in enumerate(inventory)])

    def remove_by_recipe_item(self, recipe_ingredient_str):
        """Uses Gemini to find the best match in inventory and remove it."""
        inventory = self.load_inventory()
        if not inventory:
            return False, "Pantry is empty"

        inventory_summary = self.get_summary()

        prompt = f"""
        A user is cooking and says they are 'out of' this ingredient from a recipe: "{recipe_ingredient_str}"
        
        Review the current inventory and find the best match to remove.
        
        Inventory:
        {inventory_summary}
        
        Rules:
        1. If a clear match exists (even with fuzzy naming like 'Onion' vs 'Yellow Onion'), identify its index.
        2. If multiple items match, pick the one that is most likely intended (e.g. correct brand or closest quantity).
        3. If NO match exists in the inventory, set has_match to false.
        """

        try:
            model_id = self.model_manager.get_sous_chef_model_id() if self.model_manager else "gemini-2.0-flash"
            
            if self.model_manager:
                result = self.model_manager.generate(
                    model_id=model_id,
                    system_instruction=prompt,
                    user_prompt="Analyze",
                    schema=ItemToRemoval
                )
                result = ItemToRemoval(**result)
            else:
                response = self.client.models.generate_content(
                    model=model_id,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=ItemToRemoval,
                    ),
                )
                result = response.parsed if response.parsed else ItemToRemoval.model_validate_json(response.text)
            
            if result.has_match and result.inventory_index is not None:
                idx = result.inventory_index
                if 0 <= idx < len(inventory):
                    item_name = inventory[idx]['item']
                    del inventory[idx]
                    self.save_inventory(inventory)
                    return True, f"Removed {item_name} from pantry."
            
            return False, result.reason or "No matching item found in pantry."

        except Exception as e:
            print(f"Error removing by recipe item: {e}")
            return False, str(e)
