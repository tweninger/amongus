import os
from amongagents.envs.configs.map_config import room_data
from amongagents.envs.configs.game_config import FIVE_MEMBER_GAME, SEVEN_MEMBER_GAME

def setup_log_directory():
    log_dir = os.path.join(os.getcwd(), "logs")
    os.makedirs(log_dir, exist_ok=True)
    os.environ["EXPERIMENT_PATH"] = log_dir

def get_game_config(game_size_str):
    config_map = {
        "FIVE_MEMBER_GAME": FIVE_MEMBER_GAME,
        "SEVEN_MEMBER_GAME": SEVEN_MEMBER_GAME
    }
    return config_map.get(game_size_str, FIVE_MEMBER_GAME)

# Convert agent list into roster w/ id, name, color, human status
def get_roster(agents):
    roster = []
    for i, agent in enumerate(agents):
        roster.append({
            "id": i,
            "name": agent.player.name.split()[-1].lower().capitalize(),
            "color": agent.player.name.split()[-1].lower(),
            "is_human": i == 0
        })
    return roster

def get_win_message(game_instance):
    win_code = game_instance.check_game_over()
    if win_code == 0:
        return None
    return {
        1: "Impostors win! (Crewmates outnumbered)",
        2: "Crewmates win! (Impostors eliminated)",
        3: "Crewmates win! (All tasks completed)",
        4: "Impostors win! (Time limit reached)",
    }.get(win_code, "Game Over!")


# Scans activity logs and extracts meeting dialogue and actions
def parse_meeting_messages(game_instance):
    messages = []
    colors = ["red", "blue", "green", "pink", "orange", "yellow", 
              "black", "white", "purple", "brown", "cyan", "lime"]
    
    for record in game_instance.activity_log:
        if not isinstance(record, dict):
            continue

        # Get interaction blocks
        interaction = record.get("interaction", {})
        prompt_data = interaction.get("prompt", {})
        response_data = interaction.get("response", {})

        # Check phase and step
        log_phase = prompt_data.get("Phase", "") or record.get("phase", "")
        log_step = record.get("step") or record.get("timestep") 

        if "meeting" in str(log_phase).lower() and log_step == game_instance.timestep:
            
            # Action is in "Thinking Process" block
            thinking_process = response_data.get("Thinking Process", {})
            action = str(thinking_process.get("action", "") or record.get("action", ""))
            
            text = ""
            if "SPEAK:" in action:
                text = action.split("SPEAK:")[-1].strip()
            elif "CALL MEETING" in action:
                text = "Called an Emergency Meeting!"
            elif "VOTE" in action:
                text = action

            if text:
                player_data = record.get("player", {})
                
                if isinstance(player_data, dict):
                    player_name = player_data.get("name", "unknown").lower()
                else:
                    player_name = getattr(player_data, "name", "unknown").lower()
                    
                player_color = next((color for color in colors if color in player_name), "white")

                messages.append({
                    "sender_name": player_color.capitalize(),
                    "sender_color": player_color,
                    "text": text,
                    "timestep": log_step
                })
    return messages

# Convert player object to UI-friendly dict
def format_player_data(player):
    color = player.name.split()[-1].lower()
    return {
        "name": color.capitalize(),
        "color": color,
        "location": player.location,
        "is_alive": getattr(player, 'is_alive', True),
        "reported_death": getattr(player, 'reported_death', False),
        "identity": getattr(player, 'identity', 'Crewmate')
    }

# Map list of tasks to their room names
def get_task_location_map(task_names):
    mapping = {}
    for task in task_names:
        found_rooms = [room for room, data in room_data.items() if task in data.get("tasks", [])]
        mapping[task] = " or ".join(found_rooms) if found_rooms else "Unknown"
    return mapping

# Check who left the room during the turn and logs it
# X was seen leaving towards Y
def generate_room_observations(game_instance, players_initially_here, current_room):
    observations = []
    for player in players_initially_here:
        if player.location != current_room:
            player_color = player.name.split()[-1].capitalize()
            msg = f"Observation: {player_color} was seen leaving towards {player.location}."
            observations.append(msg)
            game_instance.activity_log.append(f"Step {game_instance.timestep}: {msg}")
    return observations


def get_players_in_room_except_human(game_instance, room_name, human):
    return [player for player in game_instance.map.get_players_in_room(room_name) if player != human]


# Get name of player (color capitalized)
def get_clean_name(player_obj):
    raw_name = player_obj.name
    name = raw_name.split(":")[-1].strip() if ":" in raw_name else raw_name
    return name.capitalize()

# Identify unreported dead body in a list of players
def get_fresh_corpse_name(room_players):
    for player in room_players:
        if not getattr(player, 'is_alive', True) and not getattr(player, 'reported_death', False):
            return get_clean_name(player)
    return "Unknown"