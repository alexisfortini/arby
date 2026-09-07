from pydantic import BaseModel

# Pydantic Schemas for Structured Output
class MealDetail(BaseModel):
    name: str
    description: str | None = None
    ingredients: list[str] = []
    instructions: list[str] = []
    source: str | None = None # 'library' or 'chef'
    recipe_id: str | None = None
    image_url: str | None = None
    completed: bool = False
    rating: int = 0

class DayPlan(BaseModel):
    date: str # YYYY-MM-DD
    breakfast: MealDetail | None = None
    lunch: MealDetail | None = None
    dinner: MealDetail | None = None

class WeeklyPlan(BaseModel):
    days: list[DayPlan]
    shopping_list: list[str] = []
    summary_message: str

class PantryRecommendations(BaseModel):
    recommended_checks: list[str] 

class AssistantActionResponse(BaseModel):
    reply: str
    action_type: str = "none" # "plan_slots", "swap_meals", "set_meal", "add_grocery", "mark_cooked", "none"
    action_payload: dict = {}
 

