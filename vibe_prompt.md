# Arby AI Chef Vibe Prompt

Recreate the **Arby App**—a premium, AI-driven meal planning and kitchen assistant.

## Core Vibe
- **Aesthetic**: Premium "Chef" dashboard, clean, modern, using Slates, Blues, and soft Gradients. 
- **Tech Stack**: Python (Flask) backend, Vanilla CSS + Tailwind for styling, AlpineJS for lightweight reactivity. 
- **AI Core**: Multi-model support. Use Google Gemini as the default "Head Chef".
- **UX**: Fast, snappy, mobile-responsive, filled with micro-animations (e.g., "Cooking Up Your Plan" blobs).

## Key Features
1. **Dynamic Dashboard**: Shows active plan vs. scheduled runs. 
2. **Pantry Engine**: Smart tracking of ingredients. Supports "natural language" entry (e.g., "add 2 chicken breasts"). Use AI to parse and normalize units.
3. **Multi-Chef Planner**:
   - **Head Chef**: High-creativity models for recipes/plans.
   - **Sous Chef**: Fast models for utility tasks.
   - **Mood Integration**: "What are you in the mood for?" input affects the next plan.
4. **Live Cooking Mode**: Interactive recipe steps and ingredient checklist with persistent state.
5. **Auto-Scheduling**: Background thread that runs a weekly planning job (default: Sunday 10am) and emails the user.
6. **Cost Awareness**: Dynamic cost estimation for AI calls based on token usage and model rates.

## System Architecture
- **No Database**: Use JSON files in a `state/` directory for simplicity and portability.
- **CLI Management**: A `./arby` script for `start`, `stop`, `status`, and `logs`.
- **Modularity**: Separate concerns into `core/` (logic, managers) and `web/` (Flask server, templates).

## Design Specification
- Use the **Outfit** font from Google Fonts.
- **Color Palette**: 
  - `slate-800` for primary text.
  - `blue-600` for highlights.
  - `brand-gradient` from `#FF6B6B` to `#FF8E53`.
- **UI Elements**: Ultra-rounded corners (`rounded-3xl`), subtle glassmorphism (`backdrop-blur-sm`), and high-contrast status badges.
