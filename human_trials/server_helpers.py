import os
import json
from datetime import datetime
from db import init_db, insert_human_action, insert_game_outcome
from amongagents.envs.configs.game_config import FIVE_MEMBER_GAME
from models import WebPlayerAgent

def setup_log_directory():
    log_dir = os.path.join(os.getcwd(), "logs")
    os.makedirs(log_dir, exist_ok=True)
    os.environ["EXPERIMENT_PATH"] = log_dir


def log_human_action(game_instance, player, action_type, details=None):
    log_dir = os.environ.get("EXPERIMENT_PATH", "logs")
    log_path = os.path.join(log_dir, "human-logs.json")
    entry = {
        "game_index": f"{os.environ.get('SESSION_ID', 'unknown')}_Game {game_instance.game_index}",
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

    # Log to sqlite db too
    insert_human_action(entry)

def get_killer_of(gi, victim_name):
    for killer_name, action in gi.camera_record.items():
        if str(action).startswith("KILL") and victim_name.lower() in str(action).lower():
            return killer_name.split()[-1].lower()
    return None

def log_game_outcome(game_instance):
    log_dir = os.environ.get("EXPERIMENT_PATH", "logs")
    log_path = os.path.join(log_dir, "game-outcomes.json")

    win_code = game_instance.check_game_over()
    win_map = {
        1: ("Impostors", "crewmates_outnumbered"),
        2: ("Crewmates", "impostors_eliminated"),
        3: ("Crewmates", "tasks_completed"),
        4: ("Impostors", "time_limit_reached"),
    }
    winner, win_condition = win_map.get(win_code, ("Unknown", "unknown"))

    entry = {
        "game_index": f"{os.environ.get('SESSION_ID', 'unknown')}_Game {game_instance.game_index}",
        "timestamp": str(datetime.now()),
        "winner": winner,
        "win_condition": win_condition,
        "total_steps": game_instance.timestep,
        "players": [
            {
                "name": p.name.split()[-1].capitalize(),
                "identity": p.__class__.__name__,
                "is_alive": getattr(p, "is_alive", True),
            }
            for p in game_instance.players
        ],
    }

    with open(log_path, "a") as f:
        f.write(json.dumps(entry, indent=2) + "\n")

    insert_game_outcome(entry)

def get_game_config(game_size_str):
    return FIVE_MEMBER_GAME

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
        
        thinking_process = response_data.get("Thinking Process", {})
        action = str(thinking_process.get("action", "") or record.get("action", ""))
        is_meeting_trigger = "CALL MEETING" in action or "REPORT DEAD BODY" in action

        if ("meeting" in str(log_phase).lower() or is_meeting_trigger) and in_range:
            
            text = ""
            if "SPEAK:" in action:
                text = action.split("SPEAK:")[-1].strip()
            elif "CALL MEETING" in action:
                text = "Called an Emergency Meeting!"
            elif "REPORT DEAD BODY" in action:
                text = f"Reported a dead body at {action.split('at ')[-1]}!"
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
        "body_location": getattr(player, 'body_location', None),
        "is_alive": getattr(player, 'is_alive', True),
        "reported_death": getattr(player, 'reported_death', False),
        "identity": getattr(player, 'identity', 'Crewmate')
    }


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

# Check camera_record for KILL actions taken by players who were in the room
def generate_kill_observations(camera_record, players_initially_here):
    observations = []
    for player in players_initially_here:
        action = camera_record.get(player.name)
        if action is not None and str(action).startswith("KILL"):
            killer_color = player.name.split()[-1].capitalize()
            victim_color = str(action).split()[-1].split(":")[-1].capitalize()
            observations.append(f"Observation: {killer_color} was seen killing {victim_color}!")
    return observations

# Check camera_record for VENT actions taken by players who were in the room
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