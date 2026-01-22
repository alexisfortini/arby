# Arby 👨‍🍳 - Your Personal AI Kitchen Assistant

Arby is more than just a meal planner; it's an intelligent kitchen orchestrator designed to manage your recipes, inventory, and cooking schedule. By combining the power of Large Language Models (LLMs) with local inventory tracking, Arby helps you reduce food waste and eat better with minimal effort.

---

## 🚀 Vision & Vibe
Arby aims to be the "Sous Chef" in your pocket. It understands the context of your kitchen—what's in your pantry, what you've cooked before, and even your personal recipe library—to generate plans that actually make sense for you.

## 🛠 Features
- **Intelligent Meal Planning**: Generates multi-day plans based on your inventory and preferences.
- **Inventory Management**: Smart parsing of groceries using natural language. No more "I forgot I already had that."
- **Cookbook Ingestion**: Import your existing recipes (even from PDFs) into your local library.
- **Daily Notifications**: Receive your daily menu directly in your inbox.
- **Flexible Options**: Choose your "AI Chef" from various providers (Gemini, OpenAI, Anthropic, xAI).
- **Plan Customization**: Set specific dietary rules, family sizes, and cooking styles.

---

## 🧠 Core Concepts

### The Two Chefs Architecture
Arby uses a specialized dual-model approach to ensure high efficiency and creativity:
- **👨‍🍳 Head Chef (Brain)**: Handled by powerful models (like Gemini 1.5 Pro or GPT-4o). This chef handles the creative logic—meal planning, recipe generation, and deep context analysis.
- **🧑‍🍳 Sous Chef (Utility)**: Handled by faster, lighter models (like Gemini Flash). This chef handles structured data tasks—parsing grocery lists, matching inventory items, and extracting data from text.

### Data Context
Arby "learns" your kitchen through:
1. **Pantry Inventory**: Real-time tracking of ingredients and quantities.
2. **Recipe Library**: Your personal collection of recipes and PDF cookbooks.
3. **Meal History**: Tracking what you've cooked to avoid repetition.
4. **Vibe Prompt**: A customizable markdown file (`vibe_prompt.md`) that guides Arby's personality and tone.

---

## 📦 Installation & Setup

### 1. Prerequisites
- **Python 3.10+**
- **Pip** (Python package manager)
- **Git**

### 2. Clone the Repository
```bash
git clone https://github.com/alexisfortini/arby.git
cd arby
```

### 3. Setup Virtual Environment
```bash
python3 -m venv venv
source venv/bin/activate  # On Mac/Linux
# OR
# source ../.venv/bin/activate (if your venv is in a parent directory)
```

### 4. Initialize Local Data
Arby requires a specific JSON folder structure to save your private data. Run this script to generate the required folder structure and default config files:
```bash
python3 app/scripts/init_state.py
```

### 5. Configure Environment Variables
Copy the template file to create your own configuration:
```bash
cp .env.example .env
```
Open `.env` and fill in:
- `PDF_FOLDER`: Absolute path to your recipe PDF library.
- `EMAIL_SENDER`/`RECEIVER`: For daily meal emails (e.g., using Gmail app passwords).
- **API Keys**: We recommend storing these in your system environment variables (e.g., `~/.zshrc`) and referencing them in `.env` like `GEMINI_API_KEY="${GEMINI_API_KEY}"`. You must use the `export` keyword (e.g., `export GEMINI_API_KEY="..."`) or they won't be accessible to Arby.

### 6. Install Dependencies
```bash
pip install -r requirements.txt
```

---

## ⚡️ How to Use

### Starting the Server
Launch the application using the runner script:
```bash
./run_arby.sh
```
The web interface will be available at `http://127.0.0.1:5000`.

### Guided Walkthrough
1. **Pantry First**: Go to the **Pantry** tab and add your current staples. Try natural language like "I have 500g of spaghetti, a jar of pesto, and 3 chicken breasts."
2. **Set the Mood**: Use the **Recipe Ideas** modal on the home page to tell Arby what you're craving (e.g., "Healthy Mediterranean for the next 3 days").
3. **Generate Plan**: Click **Generate Plan**. Choose your Chef (Model) and confirm the dates.
4. **Review & Cook**: Open your active plan to see the recipes. Use **Grocery List** to see what you're missing, and **Start Cooking** for step-by-step instructions.

### Navigation Overview
- **🏠 Dashboard**: Plan status, quick links, and active plan summary.
- **📅 Calendar**: Full view of past and future plans. Toggle "Auto-Run" here.
- **🥕 Pantry**: Manage inventory and add items via camera or text.
- **📚 Library**: Your searchable cookbook, including imported PDF recipes.
- **⚙️ Settings**: Manage API keys, select default models, and set long-term preferences.

---

## 🔒 Security & Privacy
- **Local First**: Your inventory, history, and preferences stay on your machine in the `state/` folder.
- **Secure Keys**: API keys are pulled from environment variables and are never checked into version control.
- **Git Protection**: The `.gitignore` file is pre-configured to ignore `.env`, `state/`, and logs.

---

## 🛠 Troubleshooting
- **Missing State Files**: If the server errors on startup, ensure you've run `python3 app/scripts/init_state.py`.
- **API Errors**: Check your settings page connectivity status. Ensure your system environment variables are exported correctly using the `export` keyword (e.g., `export GEMINI_API_KEY="..."`).
- **Path Issues**: Ensure `PDF_FOLDER` in `.env` is an absolute path.

---

## 🤝 Contributing
Contributions are welcome! Whether it's a bug fix, a new feature, or better aesthetics, feel free to open a Pull Request.

---

*Arby Agent v1.0.0 • Crafted for better kitchens.*
