# Negotiation Game

A dynamic web-based negotiation game where players interact with characters, manage resources like influence tokens, and build or erode trust to achieve their objectives.

## Core Features

*   **Influence Mechanics**: Utilize "Influence Tokens" to perform various actions during negotiations.
*   **Trust System**: Player actions directly impact "Trust Values" with non-player characters (NPCs), affecting negotiation outcomes.
*   **Dynamic Interactions**: Experience real-time updates to game state based on your choices.
*   **Character Customization & Role Selection**: (Assumed based on template files - adjust if not applicable) Tailor your character and choose your role to influence the game's narrative.
*   **Interactive UI**: Engage with the game through a web interface that displays player stats, NPC trust levels, and available actions.

## Technology Stack

*   **Backend**: Python, Flask
*   **Frontend**: HTML, CSS (implied), JavaScript
*   **Templating**: Jinja2 (comes with Flask)

## Setup and Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/YUxiaoLLL/Negotiation-Game.git
    cd Negotiation-Game
    ```

2.  **Create and activate a virtual environment:**
    *   On macOS/Linux:
        ```bash
        python3 -m venv venv
        source venv/bin/activate
        ```
    *   On Windows:
        ```bash
        python -m venv venv
        .\venv\Scripts\activate
        ```

3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Set up Environment Variables:**
    Create a `.env` file in the root directory of the project. This file will store your secret keys and configuration settings. Add the following, replacing placeholder values with your actual credentials:
    ```env
    FLASK_APP=app.py
    FLASK_ENV=development  # Use 'production' for deployment
    FLASK_SECRET_KEY='your_super_secret_random_key_here' # Important for session management
    OPENAI_API_KEY='sk-your_openai_api_key_here' # If using OpenAI
    # Add any other necessary environment variables
    ```
    *Note: Ensure `.env` is listed in your `.gitignore` file to prevent committing secrets.*

## Running the Application

Once the setup is complete, you can run the Flask development server:

```bash
flask run
```

The application will typically be available at `http://127.0.0.1:5000/` in your web browser.

## How to Play

(Provide a brief overview of the game's objective, how to start a new game, and the basic interaction flow. For example:
*Navigate to the homepage to start a new negotiation. Select your role and customize your character. During negotiation rounds, use your influence tokens strategically to perform actions that sway NPCs and build trust. Monitor your token count and NPC trust levels to make informed decisions.*)

---

Feel free to customize the "How to Play" section and any other details to better reflect your game!
