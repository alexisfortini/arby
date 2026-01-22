from pydantic import BaseModel

# Pydantic Schemas for Structured Output
class MealDetail(BaseModel):
    name: str
    description: str | None = None
    ingredients: list[str] = []
    instructions: list[str] = []
    source: str | None = None # 'library' or 'chef'

class DayPlan(BaseModel):
    date: str # YYYY-MM-DD
    breakfast: MealDetail | None = None
    lunch: MealDetail | None = None
    dinner: MealDetail | None = None

class WeeklyPlan(BaseModel):
    days: list[DayPlan]
    shopping_list: list[str]
    summary_message: str

class PantryRecommendations(BaseModel):
    recommended_checks: list[str] 

