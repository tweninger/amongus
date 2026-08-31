import json
import os
from datetime import datetime, timezone
from pathlib import Path

from amongagents.envs.configs.game_config import FIVE_MEMBER_GAME
from db import (
    finish_game as finish_game_record,
    insert_discussion_message,
    insert_game,
    insert_game_event,
    upsert_game_players,
)
from models import WebPlayerAgent

HUMAN_TRIALS_DIR = Path(__file__).resolve().parent
DEFAULT_LOG_DIR = HUMAN_TRIALS_DIR / "logs"


def get_experiment_path() -> str:
    experiment_path = Path(os.environ.get("EXPERIMENT_PATH", DEFAULT_LOG_DIR)).expanduser()
    experiment_path.mkdir(parents=True, exist_ok=True)
    return str(experiment_path)


def setup_log_directory():
    os.environ["EXPERIMENT_PATH"] = get_experiment_path()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _game_id(game_instance) -> str:
    return str(getattr(game_instance, "game_id", game_instance.game_index))


def _player_slot(game_instance, player) -> int | None:
    try:
        return game_instance.players.index(player)
    except ValueError:
        return None


def _agent_for_slot(game_instance, slot: int | None):
    if slot is None:
        return None
    agents = game_instance.agents
    if isinstance(agents, dict):
        return agents.get(slot)
    return agents[slot] if slot < len(agents) else None


def _player_type(game_instance, player) -> str:
    return "human" if isinstance(_agent_for_slot(game_instance, _player_slot(game_instance, player)), WebPlayerAgent) else "ai"


def _color(player) -> str:
    return player.name.split()[-1].lower()


def _player_record(game_instance, player, *, consented_at=None, joined_at=None, disconnected_at=None, final=False) -> dict:
    slot = _player_slot(game_instance, player)
    agent = _agent_for_slot(game_instance, slot)
    return {
        "game_id": _game_id(game_instance),
        "player_slot": slot,
        "player_name": player.name,
        "player_color": _color(player),
        "participant_type": _player_type(game_instance, player),
        "role": getattr(player, "identity", "Unknown"),
        "model": getattr(agent, "model", None),
        "personality": getattr(player, "personality", None),
        "consented_at": consented_at,
        "joined_at": joined_at,
        "disconnected_at": disconnected_at,
        "final_is_alive": int(bool(getattr(player, "is_alive", True))) if final else None,
        "final_is_connected": int(bool(getattr(player, "is_connected", True))) if final else None,
    }


def snapshot_game_state(game_instance) -> dict:
    """Capture the decision context needed for later longitudinal analysis."""
    players = []
    for slot, player in enumerate(game_instance.players):
        tasks = [
            {
                "name": task.name,
                "location": task.location,
                "complete": task.check_completion(),
                "remaining_duration": getattr(task, "duration", None),
            }
            for task in getattr(player, "tasks", [])
        ]
        players.append(
            {
                "slot": slot,
                "name": player.name,
                "color": _color(player),
                "participant_type": _player_type(game_instance, player),
                "role": getattr(player, "identity", "Unknown"),
                "alive": bool(getattr(player, "is_alive", True)),
                "connected": bool(getattr(player, "is_connected", True)),
                "location": getattr(player, "location", None),
                "body_location": getattr(player, "body_location", None),
                "reported_death": bool(getattr(player, "reported_death", False)),
                "kill_cooldown": getattr(player, "kill_cooldown", None),
                "available_actions": [repr(action) for action in player.get_available_actions()],
                "tasks": tasks,
            }
        )
    return {
        "phase": str(getattr(game_instance, "current_phase", "")),
        "timestep": getattr(game_instance, "timestep", None),
        "meeting_number": getattr(game_instance, "meeting_number", 0),
        "emergency_buttons_used": getattr(game_instance, "button_num", None),
        "players": players,
    }


def _action_payload(action, additional_info=None) -> dict:
    payload = {"action_repr": repr(action)}
    for attribute in ("current_location", "new_location", "message"):
        value = getattr(action, attribute, None)
        if value not in (None, "..."):
            payload[attribute] = value
    target = getattr(action, "other_player", None)
    if target is not None:
        payload["target_name"] = getattr(target, "name", str(target))
    task = getattr(action, "task", None)
    if task is not None:
        payload["task_name"] = getattr(task, "name", str(task))
    if additional_info:
        payload["additional_info"] = additional_info
    return payload


def _event_type_for_action(action) -> str:
    action_name = getattr(action, "name", "UNKNOWN")
    if action_name == "CALL MEETING":
        return "REPORT" if "REPORT DEAD BODY" in repr(action) else "CALL_MEETING"
    return action_name


def record_engine_action(game_instance, player, action, additional_info=None) -> int | None:
    """Persist the engine's authoritative action record for both humans and AIs."""
    if not getattr(game_instance, "game_id", None):
        return None
    slot = _player_slot(game_instance, player)
    target = getattr(action, "other_player", None)
    event = {
        "game_id": _game_id(game_instance),
        "occurred_at": _now(),
        "timestep": getattr(game_instance, "timestep", None),
        "phase": str(getattr(game_instance, "current_phase", "")),
        "meeting_number": getattr(game_instance, "meeting_number", 0),
        "event_type": _event_type_for_action(action),
        "event_status": "executed",
        "actor_slot": slot,
        "actor_name": player.name,
        "actor_type": _player_type(game_instance, player),
        "actor_role": getattr(player, "identity", "Unknown"),
        "target_slot": _player_slot(game_instance, target) if target is not None else None,
        "target_name": getattr(target, "name", None),
        "location": getattr(player, "location", None),
        "action_name": getattr(action, "name", None),
        "payload": _action_payload(action, additional_info),
        "state_snapshot": snapshot_game_state(game_instance),
    }
    event_id = insert_game_event(event)
    message = getattr(action, "message", "").strip() if getattr(action, "name", None) == "SPEAK" else ""
    if message:
        agent = _agent_for_slot(game_instance, slot)
        insert_discussion_message(
            {
                "game_id": _game_id(game_instance),
                "event_id": event_id,
                "occurred_at": event["occurred_at"],
                "timestep": event["timestep"],
                "meeting_number": event["meeting_number"],
                "speaker_slot": slot,
                "speaker_name": player.name,
                "speaker_type": event["actor_type"],
                "speaker_role": event["actor_role"],
                "speaker_model": getattr(agent, "model", None),
                "message_text": message,
                "payload": {"action_event_id": event_id},
            }
        )
    return event_id


def record_system_event(
    game_instance,
    event_type: str,
    payload=None,
    *,
    status="executed",
    actor=None,
    target=None,
    action_name=None,
    location=None,
) -> int | None:
    if not getattr(game_instance, "game_id", None):
        return None
    actor_slot = _player_slot(game_instance, actor) if actor is not None else None
    target_slot = _player_slot(game_instance, target) if target is not None else None
    return insert_game_event(
        {
            "game_id": _game_id(game_instance),
            "occurred_at": _now(),
            "timestep": getattr(game_instance, "timestep", None),
            "phase": str(getattr(game_instance, "current_phase", "")),
            "meeting_number": getattr(game_instance, "meeting_number", 0),
            "event_type": event_type,
            "event_status": status,
            "actor_slot": actor_slot,
            "actor_name": getattr(actor, "name", None),
            "actor_type": _player_type(game_instance, actor) if actor is not None else None,
            "actor_role": getattr(actor, "identity", None),
            "target_slot": target_slot,
            "target_name": getattr(target, "name", None),
            "location": location if location is not None else getattr(actor, "location", None),
            "action_name": action_name,
            "payload": payload or {},
            "state_snapshot": snapshot_game_state(game_instance),
        }
    )


def _find_player(game_instance, identifier):
    if not isinstance(identifier, str):
        return None
    normalized = identifier.strip().lower()
    if normalized in {"", "none", "skip"}:
        return None
    return next(
        (
            player
            for player in game_instance.players
            if normalized == _color(player) or normalized == player.name.lower()
        ),
        None,
    )


def persist_game_start(game_instance, room_code: str, runtime_config: dict, code_revision: str | None, consented_at_by_slot: dict[int, str]):
    started_at = _now()
    insert_game(
        {
            "game_id": _game_id(game_instance),
            "room_code": room_code,
            "server_session_id": os.environ.get("SESSION_ID"),
            "started_at": started_at,
            "game_config": game_instance.game_config,
            "runtime_config": runtime_config,
            "code_revision": code_revision,
        }
    )
    upsert_game_players(
        [
            _player_record(
                game_instance,
                player,
                consented_at=consented_at_by_slot.get(slot),
                joined_at=started_at if _player_type(game_instance, player) == "human" else None,
            )
            for slot, player in enumerate(game_instance.players)
        ]
    )
    record_system_event(game_instance, "GAME_STARTED", {"room_code": room_code})


def log_human_action(game_instance, player, action_type, details=None):
    log_dir = get_experiment_path()
    log_path = os.path.join(log_dir, "human-logs.json")
    entry = {
        "game_index": _game_id(game_instance),
        "step": game_instance.timestep,
        "timestamp": str(datetime.now()),
        "player": {
            "name": player.name,
            "identity": getattr(player, "identity", "Unknown"),
            "location": player.location,
        },
        "action": {
            "type": action_type,
            **(details or {}),
        },
    }
    with open(log_path, "a") as f:
        f.write(json.dumps(entry, indent=2) + "\n")

    # This describes browser input. The engine separately records the executed
    # action, so analysis can distinguish submitted, timed-out, and executed work.
    details = details or {}
    target = _find_player(game_instance, details.get("target") or details.get("body"))
    record_system_event(
        game_instance,
        "ACTION_SUBMITTED",
        {"details": details},
        status="submitted",
        actor=player,
        target=target,
        action_name=action_type,
        location=getattr(player, "location", None),
    )
    if action_type == "disconnect" and getattr(game_instance, "game_id", None):
        upsert_game_players([_player_record(game_instance, player, disconnected_at=_now())])

def get_killer_of(gi, victim_name):
    for killer_name, action in gi.camera_record.items():
        if str(action).startswith("KILL") and victim_name.lower() in str(action).lower():
            return killer_name.split()[-1].lower()
    return None

def log_game_outcome(game_instance):
    log_dir = get_experiment_path()
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
        "game_index": _game_id(game_instance),
        "timestamp": str(datetime.now()),
        "winner": winner,
        "win_condition": win_condition,
        "total_steps": game_instance.timestep,
        "players": [
            {
                "name": p.name.split()[-1].capitalize(),
                "identity": getattr(p, "identity", "Unknown"),
                "is_alive": getattr(p, "is_alive", True),
                "is_connected": getattr(p, "is_connected", True),
            }
            for p in game_instance.players
        ],
    }

    with open(log_path, "a") as f:
        f.write(json.dumps(entry, indent=2) + "\n")

    upsert_game_players([_player_record(game_instance, player, final=True) for player in game_instance.players])
    finish_game_record(
        {
            "game_id": _game_id(game_instance),
            "ended_at": entry["timestamp"],
            "winner": winner,
            "win_condition": win_condition,
            "total_steps": game_instance.timestep,
        }
    )
    record_system_event(game_instance, "GAME_ENDED", {"winner": winner, "win_condition": win_condition})

def get_game_config(game_size_str):
    return FIVE_MEMBER_GAME

# Convert agent list into roster with slot status for the waiting room.
def get_roster(agents, ai_filled_slots=None):
    ai_filled_slots = ai_filled_slots or set()
    roster = []
    for i, agent in enumerate(agents):
        is_human = isinstance(agent, WebPlayerAgent)
        slot_status = "human" if is_human else ("ai" if i in ai_filled_slots else "open")
        roster.append({
            "id": i,
            "name": agent.player.name.split()[-1].lower().capitalize(),
            "color": agent.player.name.split()[-1].lower(),
            "is_human": is_human,
            "slot_status": slot_status,
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
        "is_connected": getattr(player, 'is_connected', True),
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
    return [
        player
        for player in game_instance.map.get_players_in_room(room_name)
        if player != human and getattr(player, "is_connected", True)
    ]


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
