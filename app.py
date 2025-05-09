from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import random
import os
from flask_session import Session # Import Flask-Session
from openai import OpenAI
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables from .env file
dotenv_path = Path('.') / '.env' # Explicitly point to .env in current directory
load_dotenv(dotenv_path=dotenv_path)

# --- Debug: Check if API key is loaded --- #
print(f"DEBUG: OPENAI_API_KEY loaded from environ: {os.environ.get('OPENAI_API_KEY')}")
# --- End Debug --- #

# --- Setup ---
app = Flask(__name__)
app.secret_key = os.urandom(24) # More secure secret key

# --- Server-Side Session Configuration ---
app.config['SESSION_TYPE'] = 'filesystem' # Store session data in files
app.config['SESSION_PERMANENT'] = False # Session expires when browser closes
app.config['SESSION_USE_SIGNER'] = True # Encrypt session cookie identifier
app.config['SESSION_FILE_DIR'] = './.flask_session' # Optional: Specify directory
Session(app) # Initialize the session extension

# --- OpenAI Client Setup ---
# IMPORTANT: Set the OPENAI_API_KEY environment variable!
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
if not client.api_key:
    raise ValueError("ERROR: OPENAI_API_KEY environment variable not set. Please set it in your environment or in a .env file.")

# --- Game Constants ---
MAX_ROUNDS = 8
MIN_STATEMENT_WORDS = 15 # New constant
EVENT_PROBABILITY = 0.25 # 25% chance of an event each round
TOKEN_REGEN_RATE = 2 # How many influence tokens characters regain each round
INITIAL_TRUST = 50 # Default starting trust value (0-100)
MAX_PLAYER_TOKENS = 10 # Maximum tokens the player can hold
INFLUENCE_ACTION_COSTS = {
    "gentle_persuasion": 1,
    "strong_persuasion": 2,
    "ally_recruitment": 3,
    "pressure_opponent": 4,
    "proxy_speaking": 5 # Note: Proxy speaking logic is complex, implement effects later
}
INFLUENCE_ACTION_EFFECTS = {
    # Stance delta is towards player's general alignment (support/oppose project)
    # Needs refinement - assumes player wants to pull target towards their stance.
    # Simple approach: Positive delta = more support, Negative delta = more opposition.
    # TODO: Make delta relative to player's stance vs target's stance.
    "gentle_persuasion": {"stance_delta": 5, "trust_delta": 2, "history_log": "gently persuaded"},
    "strong_persuasion": {"stance_delta": 15, "trust_delta": 10, "history_log": "strongly persuaded"},
    "ally_recruitment": {"stance_delta": 0, "trust_delta": 15, "history_log": "tried to recruit"}, # Focus on trust gain for now
    "pressure_opponent": {"stance_delta": -10, "trust_delta": -15, "history_log": "pressured"}, # Makes target more opposed/less supportive
}
MAX_TOKENS_FACTOR = 1.5 # Max tokens = initial * factor (prevents infinite hoarding)
STANCES = { # Using descriptive keys
    "support": "Support",
    "oppose": "Oppose",
    "neutral": "Neutral",
    "compromise": "Compromise"
}
NEUTRAL_SCORE = 50
SUPPORT_THRESHOLD_LOW = 61 # Score >= this means Support
OPPOSE_THRESHOLD_HIGH = 39 # Score <= this means Oppose
INITIAL_SUPPORT_SCORE = 75
INITIAL_NEUTRAL_SCORE = 50
INITIAL_OPPOSE_SCORE = 25
INFLUENCE_SCORES = {
    "developer": 2,
    "local_resident": 1,
    "council_member": 3,
    "student_representative": 1
}
VICTORY_CONSENSUS_THRESHOLD = 6 # 6 out of 10 participants
VICTORY_INFLUENCE_THRESHOLD = 9
FAILURE_SUPPORT_THRESHOLD = 2 # Player + 2 others minimum to avoid instant failure
CONSENSUS_THRESHOLD_PERCENT = 0.60 # 60% of participants must be 'Support'
INFLUENCE_THRESHOLD_PERCENT = 0.60 # 60% of *total influence* must come from 'Support'
FAILURE_SUPPORT_THRESHOLD_PERCENT = 0.25 # If 'Support' participants are <= 25%, it's a failure
CRITICAL_CLIMATE_THRESHOLD = 20 # If climate drops <= 20, it's a failure

# Sample names for AI characters
SAMPLE_NAMES = [
    "Alex Johnson", "Maria Garcia", "Chen Li", "Sam Williams", "Fatima Ahmed",
    "David Smith", "Sophia Dubois", "Kenji Tanaka", "Olivia Brown", "Mohammed Khan",
    "Isabelle Moreau", "Ben Carter", "Chloe Davis", "Raj Patel", "Zoe Miller"
]

# Define role details
ROLES = {
    "developer": {
        "name": "Developer",
        "description": "Represents the company planning the new development project.",
        "objective": "Maximize profit while meeting minimum regulatory requirements.",
        "influence": "Significant financial backing, technical expertise.",
        "stance_distribution": { STANCES["support"]: 8, STANCES["neutral"]: 2 }, # 80% support, 20% neutral
        "initial_influence_tokens": 6, # Updated
        "initial_trust": INITIAL_TRUST
    },
    "local_resident": {
        "name": "Local Resident",
        "description": "Lives in the neighborhood affected by the development.",
        "objective": "Preserve community character, minimize disruption, ensure fair compensation.",
        "influence": "Community support, personal stakes.",
        "stance_distribution": { STANCES["oppose"]: 6, STANCES["neutral"]: 4 }, # 60% oppose, 40% neutral
        "initial_influence_tokens": 2, # Updated
        "initial_trust": INITIAL_TRUST
    },
    "council_member": {
        "name": "Council Member",
        "description": "An elected official responsible for representing constituent interests.",
        "objective": "Balance development benefits with community impact, uphold regulations.",
        "influence": "Political network, regulatory power.",
        "stance_distribution": { STANCES["neutral"]: 7, STANCES["support"]: 2, STANCES["oppose"]: 1 }, # 70% neutral, 20% support, 10% oppose
        "initial_influence_tokens": 5, # Updated
        "initial_trust": INITIAL_TRUST
    },
    "student_representative": {
        "name": "Student Representative",
        "description": "Advocates for student housing and campus-related needs.",
        "objective": "Secure affordable housing options, improve campus accessibility.",
        "influence": "Represents a large demographic, potential for mobilization.",
        "stance_distribution": { STANCES["neutral"]: 5, STANCES["support"]: 4, STANCES["oppose"]: 1 }, # 50% neutral, 40% support, 10% oppose
        "initial_influence_tokens": 3, # Updated
        "initial_trust": INITIAL_TRUST
    }
}

# Micro-Story Events
MICRO_EVENTS = [
    {
        "id": "newspaper_scandal",
        "text": "Islington Daily exposes potential irregularities in the developer's past projects! Public trust wavers.",
        "effects": {"target": "role", "role_id": "local_resident", "stance_delta": -15, "climate_delta": -5}
    },
    {
        "id": "student_subsidy",
        "text": "The city government announces a surprise student housing subsidy program, boosting student optimism!",
        "effects": {"target": "role", "role_id": "student_representative", "stance_delta": +15, "climate_delta": +5}
    },
    {
        "id": "resident_emergency",
        "text": "A key Local Resident representative has a sudden family emergency and must skip this round's discussion.",
        "effects": {"target": "role_specific", "role_id": "local_resident", "skip_round": True} # Target one specific resident
    },
    {
        "id": "unexpected_endorsement",
        "text": "A respected independent urban planning group unexpectedly endorses the project's core ideas!",
        "effects": {"target": "all", "stance_delta": +10, "climate_delta": +10}
    },
    {
        "id": "developer_concession",
        "text": "The Developer offers a minor concession regarding green spaces in the plan.",
        "effects": {"target": "role", "role_id": "developer", "stance_delta": +5, "climate_delta": +5} # Small boost to developer's perceived score by others
    },
    {
        "id": "budget_cuts_rumor",
        "text": "Rumors circulate about potential city budget cuts impacting infrastructure needed for the project.",
        "effects": {"target": "all", "stance_delta": -5, "climate_delta": -10}
    },
]

def trigger_and_apply_event(characters, climate_score, current_round):
    """
    Checks if a random event should trigger based on EVENT_PROBABILITY.
    If triggered, selects a random event, applies its effects to characters
    and climate score, and returns the updated state and event text.
    Handles stance clamping (0-100) and skip_round effect.
    """
    event_triggered_info = None
    event_text = None

    if random.random() < EVENT_PROBABILITY:
        chosen_event = random.choice(MICRO_EVENTS)
        event_text = f"**Event Occurred (Round {current_round}):** {chosen_event['text']}"
        effects = chosen_event['effects']
        event_triggered_info = chosen_event # Store for potential later use/logging
        print(f"--- EVENT TRIGGERED: {chosen_event['id']} ---") # Server log

        # Apply climate delta
        climate_delta = effects.get('climate_delta', 0)
        if climate_delta != 0:
            original_climate = climate_score
            climate_score = max(0, min(100, climate_score + climate_delta))
            print(f"EVENT: Climate changed by {climate_delta} from {original_climate} to {climate_score}")

        # Identify affected characters
        stance_delta = effects.get('stance_delta', 0)
        target_type = effects.get('target')
        target_role = effects.get('role_id')
        apply_skip = effects.get('skip_round', False)
        affected_chars_for_event = []

        if target_type == 'all':
            affected_chars_for_event = characters
        elif target_type == 'role' and target_role:
            affected_chars_for_event = [char for char in characters if char['role_id'] == target_role]
        elif target_type == 'role_specific' and target_role:
             # Find all eligible characters for the specific role
             eligible_chars = [char for char in characters if char['role_id'] == target_role and not char.get('skipped_round')] # Avoid affecting already skipped
             if eligible_chars:
                 # Pick one randomly from eligible ones
                 char_to_affect = random.choice(eligible_chars)
                 affected_chars_for_event = [char_to_affect]

        # Apply effects to identified characters
        for char in affected_chars_for_event:
             # Apply stance delta
             if stance_delta != 0:
                 original_score = char['stance_score']
                 char['stance_score'] = max(0, min(100, original_score + stance_delta))
                 # Recalculate stance category after score change
                 char['stance'] = get_stance_category(char['stance_score'])
                 print(f"EVENT: Stance for {char['name']} ({char['role_id']}) changed by {stance_delta} -> {char['stance_score']} ({char['stance']})")

             # Apply skip_round effect (only applies if target was role_specific)
             if apply_skip and target_type == 'role_specific':
                 char['skipped_round'] = True # Mark character as skipping this round
                 print(f"EVENT: {char['name']} ({char['role_id']}) will skip this round due to event.")

    # Return potentially modified characters, climate, and the event message
    return characters, climate_score, event_text, event_triggered_info

# --- Helper function to derive stance category from score --- #
def get_stance_category(score):
    if score <= OPPOSE_THRESHOLD_HIGH:
        return STANCES["oppose"]
    elif score >= SUPPORT_THRESHOLD_LOW:
        return STANCES["support"]
    else:
        return STANCES["neutral"]

@app.route('/', methods=['GET', 'POST'])
def role_selection():
    if request.method == 'POST':
        player_role_id = request.form.get('role')
        if player_role_id in ROLES:
            session['player_role_id'] = player_role_id
            # Redirect to customization page
            return redirect(url_for('character_customization')) # Updated redirect
        else:
            # Handle error: invalid role selected
            return redirect(url_for('role_selection'))

    # Clear any previous session data when returning to role selection
    session.pop('player_role_id', None)
    session.pop('player_profile', None)
    return render_template('role_selection.html', roles=ROLES)

# Character Customization Route
@app.route('/customize', methods=['GET', 'POST'])
def character_customization():
    player_role_id = session.get('player_role_id')

    # Redirect back if no role was selected
    if not player_role_id or player_role_id not in ROLES:
        return redirect(url_for('role_selection'))

    player_role_name = ROLES[player_role_id]['name']

    if request.method == 'POST':
        # Collect player profile data from form
        player_profile = {
            'role_id': player_role_id,
            'role_name': player_role_name,
            'name': request.form.get('name'),
            'age': request.form.get('age'),
            'gender': request.form.get('gender'),
            'local_born': request.form.get('local_born'),
            'has_children': request.form.get('has_children'),
            'num_children': request.form.get('num_children') if request.form.get('has_children') == 'Yes' else 0,
            'marital_status': request.form.get('marital_status'),
            'backstory': request.form.get('backstory')
        }

        # Basic validation for num_children if has_children is Yes
        if player_profile['has_children'] == 'Yes' and not player_profile['num_children']:
             # Ideally, add flash message here for better UX
             return render_template('customization.html', player_role_name=player_role_name, error="Please enter the number of children.")
        try:
            player_profile['num_children'] = int(player_profile['num_children'])
            if player_profile['has_children'] == 'Yes' and player_profile['num_children'] < 1:
                raise ValueError()
        except (ValueError, TypeError):
             if player_profile['has_children'] == 'Yes':
                 return render_template('customization.html', player_role_name=player_role_name, error="Please enter a valid number of children (1 or more).")

        # Add initial player game state info
        player_profile['is_player'] = True
        player_profile['id'] = 'player_0' # Unique ID for player
        player_profile['influence'] = INFLUENCE_SCORES.get(player_role_id, 1) # Get influence score
        player_profile['initial_stance'] = STANCES["support"] # Player always supports their own goal initially
        player_profile['stance_score'] = {
            STANCES["support"]: INITIAL_SUPPORT_SCORE,
            STANCES["neutral"]: INITIAL_NEUTRAL_SCORE,
            STANCES["oppose"]: INITIAL_OPPOSE_SCORE
        }.get(player_profile['initial_stance'], INITIAL_NEUTRAL_SCORE) # Default to neutral if somehow invalid
        player_profile['influence_tokens'] = ROLES[player_role_id]['initial_influence_tokens']
        player_profile['max_tokens'] = MAX_PLAYER_TOKENS # Use the new constant
        player_profile['trust_value'] = INITIAL_TRUST
        player_profile['stance'] = get_stance_category(player_profile['stance_score']) # Set initial stance category

        session['player_profile'] = player_profile

        # Prepare full character list for negotiation
        ai_opponents = generate_ai_opponents(player_profile['role_id'])
        for opponent in ai_opponents:
            opponent['stance'] = get_stance_category(opponent['stance_score']) # Set initial stance category
        all_characters = ai_opponents + [player_profile] # Player added last before shuffle
        random.shuffle(all_characters) # Shuffle characters for display order
        session['characters'] = all_characters # Store the list

        # Initialize negotiation state
        session['negotiation_state'] = {
            'round': 1,
            'history': [], # List of rounds, each round is a dict: {'character_id': statement}
            'outcome': None, # Will store win/loss reason
            'negotiation_climate': 50 # Initial climate score (0-100)
        }

        # Redirect to negotiation stage
        return redirect(url_for('negotiation'))
        # return redirect(url_for('negotiation_group')) # Old redirect

    # For GET request, show the customization form
    return render_template('customization.html', player_role_name=player_role_name)


# Negotiation Group Display Route (Kept for potential review, but flow goes to /negotiation)
@app.route('/negotiation_group')
def negotiation_group():
    # This page is now less relevant in the main flow but can be kept for debugging
    # or showing the initial group before the first round starts.
    characters = session.get('characters')
    if not characters:
        return redirect(url_for('role_selection')) # Need characters setup first

    return render_template('negotiation_group.html', characters=characters)


# --- Negotiation Stage --- #

@app.route('/negotiation', methods=['GET', 'POST'])
def negotiation():
    # Ensure negotiation has been initialized
    if 'negotiation_state' not in session or 'characters' not in session or 'player_profile' not in session:
        flash("Game session not found or incomplete. Please start a new game.", "error")
        return redirect(url_for('role_selection'))

    negotiation_state = session['negotiation_state']
    characters = session.get('characters', [])
    player_profile = session.get('player_profile', None)
    current_round = negotiation_state['round']

    if request.method == 'POST':
        action = request.form.get('action') # Check which button was pressed

        if action == 'give_up':
            negotiation_state['outcome'] = 'Player Gave Up'
            negotiation_state['final_round'] = negotiation_state['round'] # Record when they gave up
            flash('You have chosen to end the negotiation.', 'warning')
            session['negotiation_state'] = negotiation_state
            session.modified = True
            return redirect(url_for('negotiation'))

        # If action wasn't 'give_up', assume 'submit_statement'
        player_statement = request.form.get('player_statement', '').strip()
        word_count = len(player_statement.split())

        # --- Check Minimum Word Count --- #
        if not player_statement: # Handle empty submission separately if needed
            flash('Please enter your statement.', 'warning')
            return redirect(url_for('negotiation'))
        elif word_count < MIN_STATEMENT_WORDS:
            flash(f'Your statement must be at least {MIN_STATEMENT_WORDS} words long (currently {word_count}). Please elaborate.', 'error')
            return redirect(url_for('negotiation'))

        # --- Token Cost for Statement --- #
        player_tokens = player_profile.get('influence_tokens', 0)
        if player_tokens < 1:
            flash('Not enough Influence Tokens to make a statement.', 'error')
            # Need to pass existing state back to template on redirect
            # This requires GET logic, so redirect is simpler here.
            return redirect(url_for('negotiation'))
        else:
            # Deduct token cost
            player_profile['influence_tokens'] -= 1
            # Also update the player character in the main list
            for char in characters:
                if char.get('is_player'):
                    char['influence_tokens'] = player_profile['influence_tokens']
                    break
            print(f"Player statement cost: 1 token. Remaining: {player_profile['influence_tokens']}")

        # --- Proceed with round logic only if submitting and word count is met ---
        player_id = session['player_profile']['id']

        # --- Store previous stance *category* before potential updates --- #
        # Note: We store the *category* derived from the score at the start of the round
        for char in characters:
            if not char.get('is_player'): # Only for AI characters
                # Store category based on score *before* AI response potentially changes it
                char['previous_stance_category'] = get_stance_category(char.get('stance_score', NEUTRAL_SCORE))

        if player_statement:
            round_dialogue = {player_id: player_statement} # Start round with player

            # --- Clear Previous Skip Flags & Trigger/Apply Event --- #
            for char in characters:
                char.pop('skipped_round', None) # Remove flag from previous round if set

            climate_score = negotiation_state.get('negotiation_climate', 50)
            # Get current round *before* potential event happens
            current_round = negotiation_state['round']
            characters, climate_score, event_text, _ = trigger_and_apply_event(characters, climate_score, current_round)
            negotiation_state['negotiation_climate'] = climate_score # Update climate in state
            if event_text:
                flash(event_text, 'info') # Display event message to player

            # Update characters in session *before* AI responds, so AI sees event effects
            session['characters'] = characters

            # --- Core AI Logic --- #
            ai_responses_data = get_ai_responses(characters, negotiation_state['history'], player_statement, climate_score) # Renamed variable
            round_dialogue.update({ai_id: data['response'] for ai_id, data in ai_responses_data.items()}) # Add AI statements

            # --- Update Character Stance Scores --- #
            for char in characters:
                if not char.get('is_player'): # Only update AI characters
                    ai_id = char.get('id')
                    if ai_id in ai_responses_data:
                        new_score = ai_responses_data[ai_id]['new_score']
                        old_score = char.get('stance_score', NEUTRAL_SCORE)
                        if new_score != old_score:
                            print(f"Updating stance score for {char['name']}: {old_score} -> {new_score}") # Debug print
                        char['stance_score'] = new_score # Update the score in the character list
                        char['stance'] = get_stance_category(char['stance_score']) # Update stance category

            # --- Update Negotiation Climate --- #
            total_score_change = 0
            ai_count = 0
            for char in characters:
                if not char.get('is_player'):
                    ai_id = char.get('id')
                    if ai_id in ai_responses_data:
                        old_score = char.get('stance_score', NEUTRAL_SCORE) - ai_responses_data[ai_id].get('score_change', 0) # Estimate previous score
                        new_score = char.get('stance_score', NEUTRAL_SCORE)
                        total_score_change += (new_score - old_score)
                        ai_count += 1

            if ai_count > 0:
                average_change = total_score_change / ai_count
                climate_change_factor = 2 # How much average score change affects climate
                climate_change = round(average_change * climate_change_factor)
                current_climate = negotiation_state.get('negotiation_climate', 50)
                new_climate = current_climate + climate_change
                new_climate = max(0, min(100, new_climate)) # Clamp 0-100
                negotiation_state['negotiation_climate'] = new_climate
                print(f"Climate Change: {climate_change:+}, New Climate: {new_climate}/100 (Avg Score Change: {average_change:.1f})")

            # Add the complete round dialogue to history
            negotiation_state['history'].append(round_dialogue)

            # Increment round number *before* checking victory or saving state
            negotiation_state['round'] += 1

            # Check for victory/end condition *after* updating round number
            if negotiation_state['round'] > MAX_ROUNDS:
                negotiation_state['outcome'] = check_victory(characters, negotiation_state.get('negotiation_climate', 50))

            # Save the final updated state back to session *before* redirecting
            session['negotiation_state'] = negotiation_state
            session['characters'] = characters # Save potentially updated characters (stances)
            session.modified = True # Explicitly mark session as modified

        # Redirect to GET to show updated state
        return redirect(url_for('negotiation'))

    # GET Request: Render the negotiation page
    # Save state back to session before rendering
    session['negotiation_state'] = negotiation_state
    session['characters'] = characters # Ensure characters (with previous_stance) is saved
    session.modified = True # Mark session as modified

    # Prepare characters data for template, adding the derived stance category
    characters_for_template = []
    for char in characters:
        char_copy = char.copy()
        char_copy['stance'] = get_stance_category(char.get('stance_score', NEUTRAL_SCORE))
        # Pass the stored previous category for comparison in template
        char_copy['previous_stance'] = char.get('previous_stance_category')
        characters_for_template.append(char_copy)

    climate_score = negotiation_state.get('negotiation_climate', 50) # Get climate score

    # Regenerate Influence Tokens for ALL characters
    characters = session.get('characters', [])
    player_profile = session.get('player_profile', None)
    player_char_in_list = next((char for char in characters if char.get('is_player')), None)
    if negotiation_state['round'] > 1: # Don't regen on first round entry
        print("--- Regenerating Influence Tokens ---")
        for char in characters:
            current_tokens = char.get('influence_tokens', 0)
            if char.get('is_player'):
                # Player regeneration: +1 per round, up to MAX_PLAYER_TOKENS
                regen_amount = 1 # Base regeneration for player
                bonus_token = 0 # Initialize bonus token
                # --- Award Conversion Bonus --- #
                if session.get('conversion_bonus_pending'):
                    bonus_token = 1
                    print("Awarding +1 bonus token for previous NPC conversion!")
                    session.pop('conversion_bonus_pending', None) # Consume the flag
                # --- End Conversion Bonus --- #
                total_regen = regen_amount + bonus_token
                new_tokens = min(current_tokens + total_regen, MAX_PLAYER_TOKENS)
                char['influence_tokens'] = new_tokens
                # Also update the separate player_profile dict if it exists
                if player_profile and player_profile['id'] == char['id']:
                    player_profile['influence_tokens'] = new_tokens
                    print(f"Regenerating tokens for Player: {current_tokens} + {regen_amount} (base) + {bonus_token} (bonus) -> {new_tokens} (Max: {MAX_PLAYER_TOKENS})")
            else:
                # AI regeneration: Flat rate based on TOKEN_REGEN_RATE
                regen_amount = TOKEN_REGEN_RATE # Use the flat rate defined
                max_tokens = char.get('max_tokens', int(char.get('initial_tokens', 6) * MAX_TOKENS_FACTOR))
                new_tokens = min(current_tokens + regen_amount, max_tokens)
                char['influence_tokens'] = new_tokens
                if new_tokens > current_tokens:
                     print(f"Regenerating tokens for AI {char.get('name', 'Unknown')}: {current_tokens} -> {new_tokens} (Max: {max_tokens})")
 
    # Update session data after regeneration
    session['characters'] = characters
    if player_profile: # Ensure player_profile is saved if updated
        session['player_profile'] = player_profile

    return render_template('negotiation.html',
                           state=negotiation_state,
                           characters=characters_for_template,
                           player_profile=player_profile,
                           INFLUENCE_ACTION_COSTS=INFLUENCE_ACTION_COSTS,
                           climate_score=climate_score, # Pass climate score
                           max_rounds=MAX_ROUNDS,
                           stances_map=STANCES)

# --- New Route for Viewing Profiles --- #

@app.route('/profile/<string:char_id>')
def view_profile(char_id):
    """Displays the profile details for a specific character."""
    if 'characters' not in session:
        # Or perhaps return a simple error page
        return "Character data not found in session. Please start a new game.", 404

    character_to_view = None
    for char in session['characters']:
        if char.get('id') == char_id:
            character_to_view = char
            break

    if character_to_view:
        return render_template('profile.html', character=character_to_view)
    else:
        return f"Character with ID '{char_id}' not found.", 404

# --- Core AI Logic --- #

def format_history_for_prompt(history, characters_lookup):
    """Formats the dialogue history into a readable string for the LLM prompt."""
    prompt_history = "\nDialogue History:\n"
    if not history:
        return prompt_history + "No discussion yet.\n"

    for i, round_statements in enumerate(history):
        prompt_history += f"--- Round {i+1} ---\n"
        for char_id, statement in round_statements.items():
            speaker = characters_lookup.get(char_id)
            speaker_name = speaker.get('name', 'Unknown') if speaker else 'Unknown'
            prompt_history += f"{speaker_name}: {statement}\n"
        prompt_history += "---\n"
    return prompt_history

# Function for AI Response Generation (Replaces Placeholder)
def get_ai_responses(characters, history, player_statement, climate_score):
    """Generates responses for all AI characters and calculates potential stance score changes based on AI suggestion."""
    print("\n--- Generating AI Responses --- ")
    # Filter out player AND characters skipping the round due to an event
    active_ai_characters = []
    for c in characters:
        if not c.get('is_player'):
            if c.get('skipped_round'):
                print(f"    Skipping AI response generation for {c['name']} ({c['role_id']}) due to event.")
            else:
                active_ai_characters.append(c)

    responses_data = {}
    cumulative_climate_change = 0

    for ai in active_ai_characters: # Iterate through AI characters who are participating this round
        print(f"  Generating response for: {ai['name']} ({ai['role_name']}, Stance: {ai['stance']}/{ai['stance_score']}, Inf: {ai['influence']})")

        # Prepare specific history and prompt for this AI
        ai_current_stance_category = get_stance_category(ai.get('stance_score', NEUTRAL_SCORE))
        system_prompt = (
            f"You are participating in a town hall negotiation about a new development project. "
            f"You are {ai['name']}, a {ai['role_name']}. "
            f"Your specific objective is: {ai.get('backstory', 'Objective not specified.')}. "
            f"Your current stance score towards the main proposal is: {ai.get('stance_score', NEUTRAL_SCORE)}/100 ({get_stance_category(ai.get('stance_score', NEUTRAL_SCORE))}). Higher means more supportive. "
            f"Consider your role, objectives, and the dialogue history. "
            f"Respond naturally to the latest statement(s) in the conversation. Keep your response concise (1-3 sentences). "
            f"IMPORTANT: After your dialogue, on a NEW LINE, add a score adjustment based on how the latest statement(s) affected your stance. Format EXACTLY as 'SCORE_CHANGE: +/-value' (e.g., SCORE_CHANGE: +5, SCORE_CHANGE: -3, SCORE_CHANGE: 0). The value should be between -10 and +10."
            f"The negotiation history so far is:\n{format_history_for_prompt(history, {c['id']: c for c in characters})}"
            f"The player has just said: '{player_statement}'. "
        )

        full_prompt = system_prompt

        try:
            # Make the API call
            completion = client.chat.completions.create(
                model="gpt-4.1-nano", # Use a cost-effective model suitable for simulation
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": full_prompt}
                ],
                max_tokens=80, # Keep responses concise
                temperature=0.7 # Allow some creativity
            )
            ai_response_full = completion.choices[0].message.content.strip()
            print(f"  -> Raw response received for {ai['name']}: {ai_response_full[:80]}...")

            # --- Parse AI Response for Dialogue and Score Change --- #
            ai_dialogue = ai_response_full
            score_change = 0 # Default to 0 change
            try:
                parts = ai_response_full.split('\nSCORE_CHANGE:')
                if len(parts) == 2:
                    ai_dialogue = parts[0].strip()
                    change_str = parts[1].strip()
                    score_change = int(change_str)
                    print(f"    Parsed score change for {ai['name']}: {score_change}")
                else:
                    print(f"    WARNING: Could not parse SCORE_CHANGE for {ai['name']}. Format might be incorrect. Response: {ai_response_full[:50]}...")
            except ValueError:
                print(f"    WARNING: Invalid number format for SCORE_CHANGE for {ai['name']}. Value: {change_str}")
                score_change = 0 # Reset to 0 if conversion fails
            except Exception as parse_e:
                print(f"    ERROR parsing response for {ai['name']}: {parse_e}")
                score_change = 0

            # --- Apply Suggested Stance Change --- #
            current_score = ai.get('stance_score', NEUTRAL_SCORE)
            new_score = current_score + score_change
            new_score = max(0, min(100, new_score)) # Clamp score between 0 and 100

            responses_data[ai['id']] = {
                'response': ai_dialogue, # Use the parsed dialogue
                'new_score': new_score
            }
            # --- End Stance Change Logic ---
        except Exception as e:
            print(f"ERROR generating response for {ai['name']}: {e}")
            responses_data[ai['id']] = {
                'response': f"(Error generating response for {ai['name']})",
                'new_score': ai.get('stance_score', NEUTRAL_SCORE)
            }

    print(f"--- AI Responses & Stance Updates Calculated ({len(responses_data)}/{len(active_ai_characters)}) ---")
    return responses_data

# --- Victory Check Logic --- #
def check_victory(characters, climate_score):
    """Determines the outcome of the negotiation based on final stances and potentially climate."""
    # Use derived stance category for final check
    supporters = []
    opposers = []
    total_influence = 0
    supporter_influence = 0
    total_participants = len(characters)

    for char in characters:
        stance = get_stance_category(char.get('stance_score', NEUTRAL_SCORE))
        influence = char.get('influence', 1) # Default influence to 1 if not found
        total_influence += influence
        if stance == STANCES['support']:
            supporters.append(char)
            supporter_influence += influence
        elif stance == STANCES['oppose']:
            opposers.append(char)

    # --- Implement New Victory/Failure Conditions --- #
    # 1. Consensus Victory
    if total_participants > 0 and (len(supporters) / total_participants) >= CONSENSUS_THRESHOLD_PERCENT:
        return f"Consensus Victory: Project approved with broad agreement ({len(supporters)}/{total_participants} supporters)!"

    # 2. Influence Victory
    if total_influence > 0 and (supporter_influence / total_influence) >= INFLUENCE_THRESHOLD_PERCENT:
        return f"Influence Victory: Key figures secured project approval (Supporting Influence: {supporter_influence}/{total_influence})!"

    # 3. Compromise Victory (Placeholder - requires tracking specific proposals)
    # if conditions_for_compromise_met(characters, history):
    #    return "Compromise Victory: A middle ground was found!"

    # 4. Total Failure (Critically Low Support OR Bad Climate)
    support_ratio = (len(supporters) / total_participants) if total_participants > 0 else 0
    if support_ratio <= FAILURE_SUPPORT_THRESHOLD_PERCENT:
        return f"Total Failure: Project rejected due to overwhelming opposition or apathy (Support: {len(supporters)}/{total_participants})."
    if climate_score <= CRITICAL_CLIMATE_THRESHOLD:
        return f"Total Failure: Negotiations collapsed due to a toxic climate (Climate Score: {climate_score})."

    # 5. Partial Failure (Stalemate - Default if no other condition met)
    return f"Partial Failure: Negotiation ended in stalemate. Insufficient consensus or influence reached (Support: {len(supporters)}/{total_participants}, Influence: {supporter_influence}/{total_influence}, Climate: {climate_score})."

    # 6. Public Backlash (Placeholder - requires separate mechanic)
    # if public_opinion_low:
    #    return "Failure: Public backlash halted the project."

def generate_ai_opponents(player_role_id):
    """Generates the 9 AI opponents with profiles, including initial stance and influence."""
    opponents = []
    used_names = set()
    role_counts = {
        "developer": 2,
        "local_resident": 3,
        "student_representative": 2,
        "council_member": 2
    }

    # Decrease count for player's role
    if player_role_id in role_counts:
        role_counts[player_role_id] -= 1 # Player takes one spot

    opponent_id_counter = 1 # Start AI IDs from 1
    for role_id, count in role_counts.items():
        role_info = ROLES[role_id]
        for _ in range(count):
            # Ensure unique name
            name = random.choice(SAMPLE_NAMES)
            while name in used_names:
                name = random.choice(SAMPLE_NAMES)
            used_names.add(name)

            # Determine initial stance randomly based on role distribution
            stance_dist = role_info.get('stance_distribution', { STANCES["neutral"]: 1 }) # Default to neutral if undefined
            possible_stances = list(stance_dist.keys())
            weights = list(stance_dist.values())
            chosen_initial_stance = random.choices(possible_stances, weights=weights, k=1)[0]

            # Map chosen stance to initial score
            initial_score_map = {
                STANCES["support"]: INITIAL_SUPPORT_SCORE,
                STANCES["neutral"]: INITIAL_NEUTRAL_SCORE,
                STANCES["oppose"]: INITIAL_OPPOSE_SCORE
            }
            chosen_initial_score = initial_score_map.get(chosen_initial_stance, INITIAL_NEUTRAL_SCORE)

            # Generate simple random profile for AI
            ai_profile = {
                'id': f'ai_{opponent_id_counter}', # Unique ID for AI
                'role_id': role_id,
                'role_name': role_info['name'],
                'name': name,
                'age': random.randint(20, 70),
                'gender': random.choice(['Male', 'Female', 'Other']),
                'local_born': random.choice(['Yes', 'No']),
                'has_children': random.choice(['Yes', 'No']),
                # Add simplified backstory/details based on role
                'backstory': f"Objective: {role_info['objective']}", # Simplified backstory
                'is_player': False, # Flag to differentiate AI from player
                'influence': INFLUENCE_SCORES.get(role_id, 1), # Add influence score
                'initial_stance': chosen_initial_stance, # Store the randomly chosen stance
                'stance_score': chosen_initial_score, # Set score based on chosen stance
                'stance': get_stance_category(chosen_initial_score), # Set initial stance category
                'influence_tokens': ROLES[role_id]['initial_influence_tokens'],
                'max_tokens': int(ROLES[role_id]['initial_influence_tokens'] * MAX_TOKENS_FACTOR),
                'trust_value': INITIAL_TRUST,
            }
            # Add simple logic for num_children if needed, or omit for AI
            if ai_profile['has_children'] == 'Yes':
                ai_profile['num_children'] = random.randint(1, 4)
            else:
                ai_profile['num_children'] = 0
            # Add marital status if needed
            ai_profile['marital_status'] = random.choice(['Single', 'Married', 'Other'])

            opponents.append(ai_profile)
            opponent_id_counter += 1

    return opponents

@app.route('/influence', methods=['POST'])
def influence():
    action = request.form.get('action')
    target_id = request.form.get('target_id')
    cost = INFLUENCE_ACTION_COSTS.get(action, 0)
    action_effect = INFLUENCE_ACTION_EFFECTS.get(action, {})

    # Find the target NPC in the session's character list
    characters = session.get('characters', [])
    target_npc = next((char for char in characters if char['id'] == target_id), None)

    if not target_npc:
        return jsonify({'success': False, 'message': 'Target NPC not found.'}), 404

    old_stance_score = target_npc.get('stance_score', INITIAL_NEUTRAL_SCORE)
    old_stance = get_stance_category(old_stance_score)
    old_trust = target_npc.get('trust_value', INITIAL_TRUST)

    # Apply effects (modify stance and trust)
    stance_change = action_effect.get('stance_change', 0)
    trust_change = action_effect.get('trust_change', 0)

    target_npc['stance_score'] = max(0, min(100, target_npc.get('stance_score', INITIAL_NEUTRAL_SCORE) + stance_change))
    target_npc['trust_value'] = max(0, min(100, target_npc.get('trust_value', INITIAL_TRUST) + trust_change))
    new_stance = get_stance_category(target_npc['stance_score']) # Get new stance AFTER change
    target_npc['stance'] = new_stance # Update stance category string

    print(f"Applied influence '{action}' to {target_npc['name']}. Stance: {old_stance_score} -> {target_npc['stance_score']} ({new_stance}), Trust: {old_trust} -> {target_npc['trust_value']}")

    # --- Check for Neutral -> Support Conversion --- #
    if old_stance == STANCES['neutral'] and new_stance == STANCES['support']:
        session['conversion_bonus_pending'] = True
        print(f"!!! Conversion bonus triggered for turning {target_npc['name']} supportive! Pending for next round.")
    # --- End Conversion Check --- #

    # Update player tokens
    player_profile = session.get('player_profile', None)
    if player_profile:
        player_profile['influence_tokens'] -= cost
        session['player_profile'] = player_profile

    return jsonify({'success': True, 'message': f'Influence action {action} applied to {target_npc["name"]}.'})

if __name__ == '__main__':
    # Use 0.0.0.0 to make it accessible on the network if needed, otherwise 127.0.0.1
    # Debug=True is helpful during development but should be False in production
    app.run(debug=True, host='127.0.0.1', port=5000)
