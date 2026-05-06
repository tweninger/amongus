import os
import json
from datetime import datetime
from amongagents.envs.configs.map_config import room_data
from amongagents.envs.configs.game_config import FIVE_MEMBER_GAME, SEVEN_MEMBER_GAME
from models import WebPlayerAgent

def setup_log_directory():
    log_dir = os.path.join(os.getcwd(), "logs")
    os.makedirs(log_dir, exist_ok=True)
    os.environ["EXPERIMENT_PATH"] = log_dir


def log_human_action(game_instance, player, action_type, details=None):
    log_dir = os.environ.get("EXPERIMENT_PATH", "logs")
    log_path = os.path.join(log_dir, "human-logs.json")
    entry = {
        "game_index": f"Game {game_instance.game_index}",
        "step": game_instance.timestep,
        "timestamp": str(datetime.now()),
        "player": {
            "name": player.name,
            "identity": player.__class__.__name__,
            "location": player.location,
        },
        "action": {
            "type": action_type,
            **(details or {}),
        },
    }
    with open(log_path, "a") as f:
        f.write(json.dumps(entry, indent=2) + "\n")

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
            "is_human": isinstance(agent, WebPlayerAgent)
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
# meeting_start_step: only include messages from this step onwards
def parse_meeting_messages(game_instance, meeting_start_step=None):
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

        # Did this log happen in the current meeting?
        if meeting_start_step is None:
            # If no meeting is active, we show everything
            in_range = True
        elif log_step is not None and log_step >= meeting_start_step:
            # If a meeting is active, only show logs that happened after it started
            in_range = True
        else:
            # This log is from a previous round
            in_range = False
        
        if "meeting" in str(log_phase).lower() and in_range:    
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

# Check camera_record for actual VENT actions taken by players who were in the room
def generate_vent_observations(camera_record, players_initially_here, room):
    observations = []
    for player in players_initially_here:
        if player.location == room:
            continue  # still in the room, didn't move
        action = camera_record.get(player.name)
        if action is not None and str(action).startswith("VENT"):
            player_color = player.name.split()[-1].capitalize()
            source = room.replace("_", " ")
            destination = player.location.replace("_", " ")
            observations.append(f"Observation: {player_color} was seen venting from {source} to {destination}.")
    return observations

# Identify unreported dead body in a list of players
def get_fresh_corpse_name(room_players):
    for player in room_players:
        if not getattr(player, 'is_alive', True) and not getattr(player, 'reported_death', False):
            return get_clean_name(player)
    return "Unknown"

# Returns the most recent vote result as {ejected: "blue"} or {ejected: None}
def get_latest_vote_result(game_instance):
    for record in reversed(game_instance.important_activity_log):
        action = str(record.get("action", ""))
        if "voted out" not in action.lower():
            continue
        if action.lower().startswith("no one"):
            return {"ejected": None}
        # EX: "Cyan was voted out! Detailed vote info:..."
        name_part = action.split(" was voted out")[0].strip()
        color = name_part.split()[-1].lower()
        return {"ejected": color}
    return None