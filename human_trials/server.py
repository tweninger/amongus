# server.py
import asyncio
import math
import os
import random
import re
import string
import subprocess
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import uvicorn
from amongagents.envs.action import CallMeeting, CompleteTask, Kill, MoveTo, Speak, Vent, Vote
from amongagents.envs.configs.map_config import room_data
from amongagents.envs.game import AmongUs
from db import init_db
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from models import WebPlayerAgent, skeld
from server_helpers import (
    format_player_data,
    generate_kill_observations,
    generate_room_observations,
    generate_vent_observations,
    get_clean_name,
    get_game_config,
    get_killer_of,
    get_latest_vote_result,
    get_players_in_room_except_human,
    get_roster,
    get_win_message,
    log_game_outcome,
    log_human_action,
    parse_meeting_messages,
    persist_game_start,
    record_engine_action,
    record_system_event,
    setup_log_directory,
)

# --- SETUP ---
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

# Unique ID stamped on every log entry so entries from different server sessions
# can be distinguished even when game_index resets to 0 after a restart.
os.environ['SESSION_ID'] = time.strftime("%Y%m%d_%H%M%S")
LOBBY_COUNTDOWN_SECONDS = int(os.getenv("LOBBY_COUNTDOWN_SECONDS", "60"))
LOBBY_HUMAN_PRIORITY_FRACTION = 0.75
LOBBY_AI_FILL_COMPLETE_FRACTION = 0.90
PARTICIPATION_COMPLETION_URL = os.getenv("PARTICIPATION_COMPLETION_URL", "").strip()
CONSENT_TOKEN_TTL_SECONDS = 60 * 60
MEETING_DISCUSSION_SECONDS = int(os.getenv("MEETING_DISCUSSION_SECONDS", "60"))
MEETING_VOTING_SECONDS = int(os.getenv("MEETING_VOTING_SECONDS", "60"))
AI_INITIAL_ACTION_INTERVAL_SECONDS = float(os.getenv("AI_INITIAL_ACTION_INTERVAL_SECONDS", "12"))
AI_MIN_ACTION_INTERVAL_SECONDS = float(os.getenv("AI_MIN_ACTION_INTERVAL_SECONDS", "2"))
AI_MAX_ACTION_INTERVAL_SECONDS = float(os.getenv("AI_MAX_ACTION_INTERVAL_SECONDS", "60"))
TASK_DURATION_SECONDS = max(1, int(os.getenv("TASK_DURATION_SECONDS", "20")))
MATCH_DURATION_SECONDS = max(1, int(os.getenv("MATCH_DURATION_SECONDS", "500")))
KILL_COOLDOWN_SECONDS = max(0, int(os.getenv("KILL_COOLDOWN_SECONDS", "20")))
VENT_COOLDOWN_SECONDS = max(0, int(os.getenv("VENT_COOLDOWN_SECONDS", "20")))
REALTIME_ACTION_SAFETY_LIMIT = 1_000_000


def _is_silence_message(value: object) -> bool:
    """Never send an LLM's explicit no-message choice to the discussion chat."""
    normalized = re.sub(r"^\s*\[action\]\s*", "", str(value), flags=re.IGNORECASE).strip()
    return bool(re.fullmatch(r'''(?:SPEAK\s*:\s*)?["'`]*SILENCE["'`]*[.!]?''', normalized, re.IGNORECASE))


def get_code_revision() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parent.parent,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


CODE_REVISION = get_code_revision()

# Short-lived, one-time browser tokens prove consent was explicitly accepted before matchmaking.
consent_tokens: dict[str, float] = {}


def env_model_choices(role: str) -> list[str]:
    role_prefix = role.upper()
    raw_models = (
        os.getenv(f"{role_prefix}_LLM_MODELS")
        or os.getenv(f"{role_prefix}_LLM_MODEL")
        or os.getenv("LLM_MODELS")
        or os.getenv("LLM_MODEL")
        or "gemini-3.5-flash"
    )
    return [model.strip() for model in raw_models.split(",") if model.strip()]


def build_agent_config() -> dict:
    return {
        "Impostor": "LLM",
        "Crewmate": "LLM",
        "IMPOSTOR_LLM_CHOICES": env_model_choices("impostor"),
        "CREWMATE_LLM_CHOICES": env_model_choices("crewmate"),
    }


def build_realtime_game_config(selected_config: dict) -> dict:
    """Disable the legacy turn cap in favor of the server's wall-clock match timer."""
    realtime_config = dict(selected_config)
    realtime_config["max_timesteps"] = REALTIME_ACTION_SAFETY_LIMIT
    return realtime_config

# Each GameRoom holds one game's engine, sessions, and WebSocket connections.
class GameRoom:
    def __init__(self, size_config, total_slots, host_token, host_color):
        self.game_instance = None
        self.game_id: str | None = None
        self.code: str | None = None
        self.status = "open" # "open" = joinable, "active" = game running
        self.size_config = size_config
        self.total_slots = total_slots # max num players
        self.host_token = host_token # Only the host can start the game
        self.host_color = host_color # For show in the lobby list
        self.lobby_deadline: float = 0.0 # Unix timestamp when lobby countdown expires
        self.game_started_monotonic: float | None = None
        self.match_deadline_monotonic: float | None = None
        self.match_seconds_remaining: float = float(MATCH_DURATION_SECONDS)
        self.consented_tokens: set[str] = set()
        self.consented_at_by_slot: dict[int, str] = {}
        self.ai_filled_slots: set[int] = set()
        self.lobby_fill_task: asyncio.Task | None = None
        self.sessions = {} # token -> agent index
        self.connections = {} # token -> WebSocket
        self.step_lock = asyncio.Lock() # To prevent concurrent game_step() calls
        self.meeting_running = False # Guards against double-starting the meeting loop
        self.last_phase = None # Tracks previous phase to detect transitions
        self.meeting_start_step = None # Timestep when current meeting began
        self.discussion_turn_seq = 0 # Increments each time the discussion baton passes to a new human
        self.turn_deadline: float = 0.0 # Unix timestamp when current turn expires
        self.task_timeout_task: asyncio.Task | None = None # Background sleep task for task-phase auto-submit
        self.match_timeout_task: asyncio.Task | None = None
        self.realtime_ai_scheduler_task: asyncio.Task | None = None
        self.realtime_ai_action_tasks: set[asyncio.Task] = set()
        self.realtime_ai_action_due: dict[str, float] = {}
        self.human_map_action_intervals: deque[float] = deque(maxlen=40)
        self.human_last_map_action_at: dict[str, float] = {}
        self.active_human_tasks: dict[str, dict] = {}
        self.active_player_tasks: dict[str, dict] = {}
        self.kill_cooldown_deadlines: dict[str, float] = {}
        self.vent_cooldown_deadlines: dict[str, float] = {}
        self.voting_deadline_set: bool = False # Whether the voting deadline has been set in the current meeting
        self.meeting_discussion_deadline: float = 0.0
        self.meeting_voting_open: bool = False
        self.meeting_prevote_open: bool = False
        self.meeting_discussion_started: bool = False
        self.meeting_final_vote_preparing: bool = False
        self.pre_votes: dict[str, str] = {}
        self.pending_final_votes: dict[str, str] = {}
        self.vote_influences: dict[str, list[str]] = {}
        self.meeting_thinking_players: set[str] = set()
        self.meeting_llm_tasks: set[asyncio.Task] = set()
        self.meeting_last_message_at: float = 0.0
        self.meeting_last_idle_roll_at: float = 0.0
        self.game_finished: bool = False
        self.game_outcome_logged: bool = False
        self.game_started_logged: bool = False
        self.game_events: list[dict] = []
        self.next_game_event_id: int = 1
        # A short event history lets connected clients animate vents without
        # exposing vent controls or destinations as ordinary player state.
        self.vent_events: list[dict] = []
        self.next_vent_event_id: int = 1
        self.kill_events: list[dict] = []
        self.next_kill_event_id: int = 1

# All active rooms keyed by 4 letter code
games: dict[str, GameRoom] = {}

# Reverse lookup to find a player's room from their session token
token_to_room: dict[str, str] = {}


def finish_game(room: GameRoom) -> None:
    """Stop every room-level background activity once the game has a winner."""
    if room.game_finished:
        return
    room.game_finished = True
    room.turn_deadline = 0
    if room.task_timeout_task and not room.task_timeout_task.done():
        room.task_timeout_task.cancel()
    room.task_timeout_task = None
    if (
        room.match_timeout_task
        and not room.match_timeout_task.done()
        and room.match_timeout_task is not asyncio.current_task()
    ):
        room.match_timeout_task.cancel()
    room.match_timeout_task = None
    stop_realtime_task_phase(room)
    cancel_meeting_llm_tasks(room)

# Generates 4 letter random key code
def generate_room_code():
    return ''.join(random.choices(string.ascii_uppercase, k=4))


def get_lobby_seconds_left(room: GameRoom) -> int:
    if room.status != "open" or room.lobby_deadline <= 0:
        return 0
    return max(0, int(room.lobby_deadline - time.time()))


def all_human_participants_consented(room: GameRoom) -> bool:
    return bool(room.sessions) and set(room.sessions).issubset(room.consented_tokens)


def start_lobby_countdown_if_ready(room: GameRoom) -> None:
    if (
        room.status == "open"
        and room.lobby_deadline <= 0
        and all_human_participants_consented(room)
    ):
        room.lobby_deadline = time.time() + LOBBY_COUNTDOWN_SECONDS
        room.lobby_fill_task = asyncio.create_task(run_lobby_countdown(room))


def consume_consent_token(token: object) -> None:
    token = str(token or "")
    issued_at = consent_tokens.pop(token, None)
    if issued_at is None or time.time() - issued_at > CONSENT_TOKEN_TTL_SECONDS:
        raise HTTPException(status_code=403, detail="Informed consent is required before joining a game.")


def get_open_slots(room: GameRoom) -> list[int]:
    taken = set(room.sessions.values()) | room.ai_filled_slots
    return [i for i in range(room.total_slots) if i not in taken]


def get_filled_slot_count(room: GameRoom) -> int:
    return len(room.sessions) + len(room.ai_filled_slots)


def is_room_full(room: GameRoom) -> bool:
    return get_filled_slot_count(room) >= room.total_slots


def add_game_event(room: GameRoom, message: str, event_type: str = "info") -> None:
    room.game_events.append({
        "id": room.next_game_event_id,
        "timestep": room.game_instance.timestep if room.game_instance else 0,
        "message": message,
        "type": event_type,
    })
    room.next_game_event_id += 1
    room.game_events = room.game_events[-25:]


def add_vent_event(room: GameRoom, player, source_room: str, destination_room: str) -> None:
    """Publish a bounded, presentation-only record for a visible vent."""
    room.vent_events.append({
        "id": room.next_vent_event_id,
        "player_color": str(player.name).split(":")[-1].strip().lower(),
        "source_room": source_room.lower(),
        "destination_room": destination_room.lower(),
    })
    room.next_vent_event_id += 1
    room.vent_events = room.vent_events[-10:]


def add_kill_event(room: GameRoom, killer, target, room_name: str) -> None:
    """Publish a bounded, presentation-only record for a visible kill."""
    room.kill_events.append({
        "id": room.next_kill_event_id,
        "killer_color": str(killer.name).split(":")[-1].strip().lower(),
        "target_color": str(target.name).split(":")[-1].strip().lower(),
        "room": room_name.lower(),
    })
    room.next_kill_event_id += 1
    room.kill_events = room.kill_events[-10:]


async def activate_room(room: GameRoom, reason: str) -> None:
    if (
        not room.game_instance
        or room.status != "open"
        or not is_room_full(room)
        or not all_human_participants_consented(room)
    ):
        return

    if room.lobby_fill_task and room.lobby_fill_task is not asyncio.current_task():
        room.lobby_fill_task.cancel()
    room.lobby_fill_task = None
    room.lobby_deadline = 0
    room.status = "active"
    room.game_started_monotonic = time.monotonic()
    room.match_seconds_remaining = float(MATCH_DURATION_SECONDS)
    room.match_deadline_monotonic = room.game_started_monotonic + MATCH_DURATION_SECONDS
    room.game_instance.game_phase = "active"
    room.game_instance.activity_log.append(reason)
    if not room.game_started_logged:
        persist_game_start(
            room.game_instance,
            room.code or "unknown",
            {
                "lobby_countdown_seconds": LOBBY_COUNTDOWN_SECONDS,
                "task_play_mode": "realtime",
                "ai_initial_action_interval_seconds": AI_INITIAL_ACTION_INTERVAL_SECONDS,
                "ai_min_action_interval_seconds": AI_MIN_ACTION_INTERVAL_SECONDS,
                "ai_max_action_interval_seconds": AI_MAX_ACTION_INTERVAL_SECONDS,
                "match_duration_seconds": MATCH_DURATION_SECONDS,
                "meeting_discussion_seconds": MEETING_DISCUSSION_SECONDS,
                "meeting_voting_seconds": MEETING_VOTING_SECONDS,
                "llm_provider": os.getenv("LLM_PROVIDER"),
                "llm_models": env_model_choices("crewmate"),
                "impostor_llm_models": env_model_choices("impostor"),
            },
            CODE_REVISION,
            room.consented_at_by_slot,
        )
        room.game_started_logged = True

    await broadcast_lobby(room, event="game_started")
    start_realtime_task_phase(room)
    room.match_timeout_task = asyncio.create_task(run_match_countdown(room))
    await broadcast_state(room)


async def run_match_countdown(room: GameRoom) -> None:
    """End an active match when its wall-clock duration expires."""
    try:
        while not room.game_finished and room.game_instance and room.status == "active":
            if room.match_deadline_monotonic is None:
                await asyncio.sleep(0.25)
                continue

            seconds_left = room.match_deadline_monotonic - time.monotonic()
            if seconds_left > 0:
                await asyncio.sleep(min(seconds_left, 0.25))
                continue

            room.match_seconds_remaining = 0.0
            room.game_instance.match_time_expired = True
            await broadcast_state(room)
            return
    except asyncio.CancelledError:
        return


async def run_lobby_countdown(room: GameRoom) -> None:
    fill_phase_start = room.lobby_deadline - (LOBBY_COUNTDOWN_SECONDS * (1.0 - LOBBY_HUMAN_PRIORITY_FRACTION))
    fill_phase_end = room.lobby_deadline - (LOBBY_COUNTDOWN_SECONDS * (1.0 - LOBBY_AI_FILL_COMPLETE_FRACTION))
    fill_window_seconds = max(0.5, fill_phase_end - fill_phase_start)

    try:
        delay = max(0.0, fill_phase_start - time.time())
        if delay > 0:
            await asyncio.sleep(delay)

        while room.status == "open":
            open_slots = get_open_slots(room)
            if not open_slots:
                await activate_room(room, "Lobby filled. Starting game.")
                return

            if time.time() >= fill_phase_end:
                room.ai_filled_slots.update(open_slots)
                await broadcast_lobby(room)
                await activate_room(room, "Lobby filled with AI. Starting game.")
                return

            remaining_fill_window = max(0.1, fill_phase_end - time.time())
            average_delay = max(0.25, min(fill_window_seconds, remaining_fill_window) / len(open_slots))
            sleep_for = min(remaining_fill_window, max(0.25, average_delay * random.uniform(0.6, 1.4)))
            await asyncio.sleep(sleep_for)

            if room.status != "open":
                return

            open_slots = get_open_slots(room)
            if not open_slots:
                await activate_room(room, "Lobby filled. Starting game.")
                return

            room.ai_filled_slots.add(random.choice(open_slots))
            await broadcast_lobby(room)

        if room.status == "open" and is_room_full(room):
            await activate_room(room, "Lobby filled. Starting game.")
    except asyncio.CancelledError:
        return

app = FastAPI()

# Security and setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# File Paths
current_dir = Path(__file__).resolve().parent
static_path = current_dir / "static"
assets_path = current_dir / "assets"
game_template_path = current_dir / "templates" / "game.html"
map_editor_template_path = current_dir / "templates" / "map_editor.html"

# Serve static and asset files 
app.mount("/static", StaticFiles(directory=static_path), name="static")
app.mount("/assets", StaticFiles(directory=assets_path), name="assets")

# --- Global HELPER ---
# More helpers in server_helpers.py

# Get GameRoom given session token
# GameRoom is the main object that holds the game instance, sessions, and connections for a particular game
def get_room(token: str) -> GameRoom | None:
    code = token_to_room.get(token)
    if code:
        return games.get(code)
    return None

# Given a session token, return the player's WebPlayerAgent
# WebPlayerAgent allows the server to check the player's current state in the game instance and queue their next action
def get_human_agent(token: str) -> WebPlayerAgent | None:
    room = get_room(token)
    if not room or not room.game_instance:
        return None
    players_idx = room.sessions.get(token)
    # Return the corresponding agent from the game instance
    if players_idx is not None:
        return room.game_instance.agents[players_idx]
    return None

# Take the next agent slot not yet claimed by a human player
# An index i
def get_next_open_slot(room: GameRoom) -> int | None:
    taken = set(room.sessions.values()) | room.ai_filled_slots
    for i, agent in enumerate(room.game_instance.agents):
        if i not in taken and not isinstance(agent, WebPlayerAgent):
            return i
    return None

def pause_match_clock(room: GameRoom) -> None:
    """Preserve the remaining match time while a meeting is in progress."""
    if room.match_deadline_monotonic is None:
        return
    room.match_seconds_remaining = max(0.0, room.match_deadline_monotonic - time.monotonic())
    room.match_deadline_monotonic = None


def resume_match_clock(room: GameRoom) -> None:
    """Resume the match clock after a meeting without charging meeting time."""
    if room.match_deadline_monotonic is not None or room.game_finished:
        return
    room.match_deadline_monotonic = time.monotonic() + room.match_seconds_remaining


def _match_seconds_left(room: GameRoom) -> int:
    return math.ceil(
        max(
            0.0,
            room.match_deadline_monotonic - time.monotonic()
            if room.match_deadline_monotonic is not None
            else room.match_seconds_remaining,
        )
    )


def _refresh_ai_match_time_context(room: GameRoom) -> None:
    """Route the current wall-clock budget into each AI's next decision prompt."""
    gi = room.game_instance
    gi.match_seconds_left = _match_seconds_left(room)
    gi.match_duration_seconds = MATCH_DURATION_SECONDS
    gi.update_map()


# Track meeting phase transitions on the room object.
# Private helper used in broadcast_state.
def _update_meeting_tracking(room: GameRoom, gi, current_phase: str) -> None:
    # Meeting start
    if current_phase == "meeting" and room.last_phase != "meeting":
        pause_match_clock(room)
        room.meeting_start_step = gi.timestep
        room.discussion_turn_seq = 0
        room.turn_deadline = 0
        room.meeting_discussion_deadline = 0
        room.meeting_voting_open = False
        room.meeting_prevote_open = False
        room.meeting_discussion_started = False
        room.meeting_final_vote_preparing = False
        room.pre_votes.clear()
        room.pending_final_votes.clear()
        room.vote_influences.clear()
        if room.task_timeout_task and not room.task_timeout_task.done():
            room.task_timeout_task.cancel()
            room.task_timeout_task = None
    # Meeting end
    elif current_phase != "meeting" and room.last_phase == "meeting":
        resume_match_clock(room)
        room.meeting_start_step = None
        room.discussion_turn_seq = 0
        room.meeting_discussion_deadline = 0
        room.meeting_voting_open = False
        room.meeting_prevote_open = False
        room.meeting_discussion_started = False
        room.meeting_final_vote_preparing = False
        cancel_meeting_llm_tasks(room)

    room.last_phase = current_phase

# Is it a specific player's turn given the current meeting state?
# This accounts for both voting and discussion
def _is_player_turn(agent, is_alive: bool, current_phase: str, can_vote: bool) -> bool:
    if current_phase != "meeting":
        return True  # Task phase: no such thing as a turn
    if can_vote:
        return is_alive  # Only if alive!

    # During shared discussion every living participant may speak at any time.
    return is_alive


def get_meeting_turn_player(gi, current_phase: str, can_vote: bool) -> dict | None:
    if current_phase != "meeting" or can_vote:
        return None

    current_name = getattr(gi, "current_player", None)
    if not current_name:
        return None

    player = next((candidate for candidate in gi.players if candidate.name == current_name), None)
    if not player or not is_connected_player(player):
        return None

    data = format_player_data(player)
    data.pop("identity", None)
    return data


def is_connected_player(player) -> bool:
    return getattr(player, "is_connected", True)


def format_realtime_player_data(room: GameRoom, player) -> dict:
    data = format_player_data(player)
    data["is_tasking"] = player.name in room.active_player_tasks
    return data


def mark_active_player_disconnected(room: GameRoom, token: str):
    gi = room.game_instance
    if not gi:
        return None

    idx = room.sessions.pop(token, None)
    if idx is None:
        return None

    agent = gi.agents[idx]
    player = agent.player
    player.is_connected = False
    player.available_actions = []
    player.body_location = None
    player.reported_death = True
    player.killed_this_step = False

    if isinstance(agent, WebPlayerAgent):
        agent.queued_action = None
        agent.waiting_for_action = False
        agent._prev_waiting = False

    log_human_action(gi, player, "disconnect")
    player_color = player.name.split()[-1].capitalize()
    add_game_event(room, f"{player_color} disconnected.", "warning")
    gi.update_map()
    return agent


# Broadcast current game state to all connected players in a room
# This includes player states, phase, timestep, task progress, win status, and meeting context when relevant
async def broadcast_state(room: GameRoom):
    gi = room.game_instance
    if not gi:
        return

    current_phase = str(gi.current_phase).lower()
    can_vote = current_phase == "meeting" and room.meeting_voting_open
    _update_meeting_tracking(room, gi, current_phase)

    turn_seconds_left = max(0, int(room.turn_deadline - time.time())) if room.turn_deadline > 0 else None
    match_seconds_left = _match_seconds_left(room)
    winner = get_win_message(gi)
    players_data = [
        format_realtime_player_data(room, agent.player)
        for agent in gi.agents
        if is_connected_player(agent.player)
    ]
    if not winner:
        for p in players_data:
            p.pop("identity", None)
    payload = {
        "type": "state_update",
        "players": players_data,
        "timestep": gi.timestep,
        "phase": current_phase,
        "task_progress": gi.task_assignment.check_task_completion(),
        "winner": winner,
        "participation_completion_url": PARTICIPATION_COMPLETION_URL if winner else "",
        "vote_result": get_latest_vote_result(gi),
        "meeting_messages": parse_meeting_messages(gi, room.meeting_start_step) if current_phase == "meeting" else [],
        "can_vote": can_vote,
        "pre_vote_open": current_phase == "meeting" and room.meeting_prevote_open,
        "final_vote_preparing": current_phase == "meeting" and room.meeting_final_vote_preparing,
        "discussion_open": (
            current_phase == "meeting"
            and room.meeting_running
            and not room.meeting_voting_open
            and time.time() < room.meeting_discussion_deadline
        ),
        "discussion_turn_seq": room.discussion_turn_seq,
        "meeting_turn_player": get_meeting_turn_player(gi, current_phase, can_vote),
        "thinking_players": [
            format_player_data(agent.player)
            for agent in gi.agents
            if agent.player.name in room.meeting_thinking_players
            and getattr(agent.player, "is_alive", True)
            and is_connected_player(agent.player)
        ],
        "turn_seconds_left": turn_seconds_left,
        "match_seconds_left": match_seconds_left,
        "match_clock_paused": current_phase == "meeting",
        "game_events": room.game_events,
        "vent_events": room.vent_events,
        "kill_events": room.kill_events,
    }

    if payload["winner"] and not room.game_outcome_logged:
        room.game_outcome_logged = True
        log_game_outcome(gi)
    if payload["winner"]:
        finish_game(room)

    dead = []

    # Iterate through connections and send the current state.
    for token, ws in room.connections.items():
        try:
            idx = room.sessions.get(token)
            agent = gi.agents[idx] if idx is not None else None
            is_alive = (
                getattr(agent.player, 'is_alive', True)
                and is_connected_player(agent.player)
                if agent else True
            )
            is_my_turn = _is_player_turn(agent, is_alive, current_phase, can_vote)
            killed_by = get_killer_of(gi, agent.player.name) if agent and not is_alive else None
            player_name = agent.player.name if agent else ""
            await ws.send_json({
                **payload,
                "is_alive": is_alive,
                "is_my_turn": is_my_turn,
                "killed_by": killed_by,
                "pre_vote_submitted": player_name in room.pre_votes,
                "pre_votes_remaining": max(0, len(_meeting_voters(gi)) - len(room.pre_votes)),
                "final_vote_selected": player_name in room.pending_final_votes,
                "vote_influence_submitted": player_name in room.vote_influences,
            })
        except Exception:
            # Mark for removal if send fails (client disconnected)
            dead.append(token)
    for t in dead:
        room.connections.pop(t, None)

# Push a lobby event (roster update or game_started) to all waiting players
async def broadcast_lobby(room: GameRoom, event: str = "lobby_update") -> None:
    if not room.game_instance:
        return
    payload = {
        "type": event,
        "roster": get_roster(room.game_instance.agents, room.ai_filled_slots),
        "lobby_seconds_left": get_lobby_seconds_left(room),
        "filled_slots": get_filled_slot_count(room),
        "total_slots": room.total_slots,
    }
    dead = []
    for token, ws in room.connections.items():
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(token)
    for t in dead:
        room.connections.pop(t, None)


def _matching_current_task_action(gi, player, proposed_action):
    """Return a fresh equivalent action, or None if a delayed decision is stale."""
    gi.check_actions()
    for candidate in player.get_available_actions():
        if candidate.name != getattr(proposed_action, "name", None):
            continue
        if hasattr(candidate, "new_location"):
            if candidate.new_location == getattr(proposed_action, "new_location", None):
                return candidate
        elif hasattr(candidate, "task"):
            proposed_task = getattr(proposed_action, "task", None)
            if proposed_task and candidate.task.name == proposed_task.name:
                return candidate
        elif hasattr(candidate, "other_player"):
            proposed_target = getattr(proposed_action, "other_player", None)
            if proposed_target and candidate.other_player is proposed_target:
                return candidate
        else:
            return candidate
    return None


def _cooldown_seconds_left(deadlines: dict[str, float], player) -> int:
    return max(0, math.ceil(deadlines.get(player.name, 0.0) - time.monotonic()))


def _action_cooldown_seconds_left(room: GameRoom, player, action_name: object) -> int:
    if action_name == "KILL":
        return _cooldown_seconds_left(room.kill_cooldown_deadlines, player)
    if action_name == "VENT":
        return _cooldown_seconds_left(room.vent_cooldown_deadlines, player)
    return 0


def _start_action_cooldown(room: GameRoom, player, action_name: str) -> None:
    if action_name == "KILL":
        room.kill_cooldown_deadlines[player.name] = time.monotonic() + KILL_COOLDOWN_SECONDS
        # The simulation's historical action-count cooldown is not used in realtime play.
        player.kill_cooldown = 0
    elif action_name == "VENT":
        room.vent_cooldown_deadlines[player.name] = time.monotonic() + VENT_COOLDOWN_SECONDS


def _record_human_map_action(room: GameRoom, player) -> None:
    now = time.monotonic()
    previous = room.human_last_map_action_at.get(player.name)
    if previous is not None:
        interval = now - previous
        if interval <= AI_MAX_ACTION_INTERVAL_SECONDS * 2:
            room.human_map_action_intervals.append(interval)
    room.human_last_map_action_at[player.name] = now


def _human_map_action_interval(room: GameRoom) -> float:
    if not room.human_map_action_intervals:
        return AI_INITIAL_ACTION_INTERVAL_SECONDS
    average = sum(room.human_map_action_intervals) / len(room.human_map_action_intervals)
    return min(AI_MAX_ACTION_INTERVAL_SECONDS, max(AI_MIN_ACTION_INTERVAL_SECONDS, average))


def _route_task_started_observation(gi, player, task_name: str) -> None:
    """Let present players observe task work just as they observe map actions."""
    location = player.location
    message = (
        f"Event {gi.timestep}: [task phase] {player.name} started working on "
        f"{task_name} in {location}."
    )
    for observer in gi.players:
        if (
            observer is not player
            and is_connected_player(observer)
            and getattr(observer, "location", None) == location
        ):
            observer.receive(message, "action")


async def start_meeting_if_needed(room: GameRoom) -> None:
    async with room.step_lock:
        if (
            room.game_finished
            or not room.game_instance
            or str(room.game_instance.current_phase).lower() != "meeting"
            or room.meeting_running
        ):
            return
        room.meeting_running = True
        asyncio.create_task(run_meeting_step(room))


async def execute_realtime_task_action(
    room: GameRoom,
    agent,
    proposed_action,
    *,
    human_submission: tuple[str, dict] | None = None,
    track_human_rate: bool = True,
):
    """Validate and apply one task action without waiting for other players."""
    gi = room.game_instance
    player = agent.player
    meeting_started = False
    async with room.step_lock:
        if room.game_finished or str(gi.current_phase).lower() != "task":
            raise HTTPException(status_code=400, detail="The task phase is no longer active.")
        if not is_connected_player(player):
            raise HTTPException(status_code=403, detail="Disconnected players cannot act.")

        proposed_action_name = getattr(proposed_action, "name", None)
        cooldown_seconds = _action_cooldown_seconds_left(room, player, proposed_action_name)
        if cooldown_seconds:
            raise HTTPException(
                status_code=400,
                detail=f"{proposed_action_name.title()} is on cooldown for {cooldown_seconds}s.",
            )

        action = _matching_current_task_action(gi, player, proposed_action)
        if action is None:
            raise HTTPException(status_code=400, detail="That action is no longer available.")

        if human_submission is not None:
            action_type, details = human_submission
            if action_type != "COMPLETE_TASK":
                room.active_human_tasks.pop(player.name, None)
                room.active_player_tasks.pop(player.name, None)
            log_human_action(gi, player, action_type, details)
            if track_human_rate:
                _record_human_map_action(room, player)

        gi.camera_record = {
            current_player.name: "stand quietly and do nothing"
            for current_player in gi.players
            if is_connected_player(current_player)
        }
        source_room = player.location
        kill_target = action.other_player if getattr(action, "name", None) == "KILL" else None
        agent.queued_action = action
        await gi.agent_step(agent)
        if getattr(action, "name", None) == "VENT":
            add_vent_event(room, player, source_room, player.location)
        if kill_target is not None:
            add_kill_event(room, player, kill_target, source_room)
        _start_action_cooldown(room, player, getattr(action, "name", ""))
        gi.timestep += 1
        meeting_started = str(gi.current_phase).lower() == "meeting"

    if meeting_started:
        await start_meeting_if_needed(room)
    await broadcast_state(room)
    return action


async def run_realtime_ai_action(room: GameRoom, agent) -> None:
    gi = room.game_instance
    player = agent.player
    task_activity_started = False
    try:
        if (
            room.game_finished
            or str(gi.current_phase).lower() != "task"
            or not getattr(player, "is_alive", True)
            or not is_connected_player(player)
        ):
            return
        _refresh_ai_match_time_context(room)
        gi.check_actions()
        print(f"[AI map action] request started for {player.name}", flush=True)
        action = await asyncio.wait_for(agent.choose_action(gi.timestep), timeout=120.0)
        if action is not None:
            cooldown_seconds = _action_cooldown_seconds_left(room, player, getattr(action, "name", None))
            if cooldown_seconds:
                print(
                    f"[AI map action] {player.name} skipped {action.name}; "
                    f"{cooldown_seconds}s remaining.",
                    flush=True,
                )
                return
            if getattr(action, "name", None) in {"COMPLETE TASK", "COMPLETE FAKE TASK"}:
                room.active_player_tasks[player.name] = {
                    "task_name": action.task.name,
                    "location": player.location,
                    "started_at": time.monotonic(),
                }
                task_activity_started = True
                record_system_event(
                    gi,
                    "TASK_STARTED",
                    {
                        "task": action.task.name,
                        "location": player.location,
                        "duration_seconds": TASK_DURATION_SECONDS,
                    },
                    status="started",
                    actor=player,
                    action_name=action.name,
                )
                _route_task_started_observation(gi, player, action.task.name)
                await broadcast_state(room)
                print(
                    f"[AI map action] {player.name} is working on {action.task.name} "
                    f"for {TASK_DURATION_SECONDS}s",
                    flush=True,
                )
                await asyncio.sleep(TASK_DURATION_SECONDS)
                if (
                    room.game_finished
                    or str(gi.current_phase).lower() != "task"
                    or not getattr(player, "is_alive", True)
                ):
                    return
                room.active_player_tasks.pop(player.name, None)
                task_activity_started = False
            await execute_realtime_task_action(room, agent, action)
    except asyncio.CancelledError:
        raise
    except HTTPException as error:
        print(f"[AI map action] stale action discarded for {player.name}: {error.detail}", flush=True)
    except Exception as error:
        print(f"[AI map action] failed for {player.name}: {error}", flush=True)
    finally:
        if task_activity_started:
            room.active_player_tasks.pop(player.name, None)
        room.realtime_ai_action_due[player.name] = (
            time.monotonic() + _human_map_action_interval(room) * random.uniform(0.8, 1.2)
        )


async def realtime_ai_action_loop(room: GameRoom) -> None:
    try:
        while (
            not room.game_finished
            and room.game_instance
            and str(room.game_instance.current_phase).lower() == "task"
        ):
            now = time.monotonic()
            for agent in room.game_instance.agents:
                player = agent.player
                if (
                    isinstance(agent, WebPlayerAgent)
                    or not getattr(player, "is_alive", True)
                    or not is_connected_player(player)
                ):
                    continue
                if player.name not in room.realtime_ai_action_due:
                    room.realtime_ai_action_due[player.name] = (
                        now + _human_map_action_interval(room) * random.uniform(0.6, 1.4)
                    )
                if now < room.realtime_ai_action_due[player.name]:
                    continue
                if any(not task.done() and task.get_name() == player.name for task in room.realtime_ai_action_tasks):
                    continue
                task = asyncio.create_task(run_realtime_ai_action(room, agent), name=player.name)
                room.realtime_ai_action_tasks.add(task)
                task.add_done_callback(room.realtime_ai_action_tasks.discard)
            await asyncio.sleep(0.25)
    except asyncio.CancelledError:
        return


def start_realtime_task_phase(room: GameRoom) -> None:
    if room.game_finished or not room.game_instance or str(room.game_instance.current_phase).lower() != "task":
        return
    room.turn_deadline = 0
    if room.task_timeout_task and not room.task_timeout_task.done():
        room.task_timeout_task.cancel()
    room.task_timeout_task = None
    if room.realtime_ai_scheduler_task and not room.realtime_ai_scheduler_task.done():
        return
    room.realtime_ai_action_due.clear()
    room.realtime_ai_scheduler_task = asyncio.create_task(realtime_ai_action_loop(room))


def stop_realtime_task_phase(room: GameRoom) -> None:
    if room.realtime_ai_scheduler_task and not room.realtime_ai_scheduler_task.done():
        room.realtime_ai_scheduler_task.cancel()
    room.realtime_ai_scheduler_task = None
    current_task = asyncio.current_task()
    for task in tuple(room.realtime_ai_action_tasks):
        if task is not current_task:
            task.cancel()
    room.realtime_ai_action_tasks.clear()
    room.realtime_ai_action_due.clear()


def cancel_meeting_llm_tasks(room: GameRoom) -> None:
    for task in tuple(room.meeting_llm_tasks):
        task.cancel()
    room.meeting_llm_tasks.clear()
    room.meeting_thinking_players.clear()


def start_llm_meeting_speech(room: GameRoom, agent, reason: str) -> None:
    if agent.player.name in room.meeting_thinking_players:
        return
    # Mark before creating the task. Otherwise a second message can schedule the
    # same agent again before its coroutine first gets a chance to run.
    room.meeting_thinking_players.add(agent.player.name)
    print(f"Scheduling meeting reply from {agent.player.name} ({reason}).")
    task = asyncio.create_task(generate_llm_meeting_speech(room, agent))
    room.meeting_llm_tasks.add(task)
    task.add_done_callback(room.meeting_llm_tasks.discard)


def schedule_llm_speech_rolls(room: GameRoom) -> None:
    """Give each available LLM a 1 / alive-player-count chance to answer a message."""
    gi = room.game_instance
    if (
        not gi
        or room.meeting_voting_open
        or str(gi.current_phase).lower() != "meeting"
        or time.time() >= room.meeting_discussion_deadline
    ):
        return

    alive_agents = [
        agent for agent in gi.agents
        if getattr(agent.player, "is_alive", True) and is_connected_player(agent.player)
    ]
    if not alive_agents:
        return

    for agent in alive_agents:
        if isinstance(agent, WebPlayerAgent) or agent.player.name in room.meeting_thinking_players:
            continue
        if random.random() >= 1 / len(alive_agents):
            continue
        start_llm_meeting_speech(room, agent, "message roll")


def get_meeting_reporter(gi):
    for record in reversed(gi.activity_log):
        if not isinstance(record, dict):
            continue
        action = record.get("action")
        if getattr(action, "name", None) == "CALL MEETING":
            return record.get("player")
    return None


def _meeting_voters(gi):
    return [
        agent for agent in gi.agents
        if getattr(agent.player, "is_alive", True) and is_connected_player(agent.player)
    ]


def _find_vote_target(gi, choice, *, allow_self=True, actor=None):
    if not isinstance(choice, str):
        return None
    normalized = choice.strip().lower()
    if normalized in {"", "none", "unknown", "i do not know", "skip"}:
        return None
    for player in gi.players:
        if (
            getattr(player, "is_alive", True)
            and is_connected_player(player)
            and (allow_self or player is not actor)
            and (normalized == player.name.lower() or normalized == player.name.split()[-1].lower())
        ):
            return player
    return None


def _parse_llm_choice(response, candidates):
    text = str(response).lower()
    for candidate in candidates:
        if candidate.lower() in text:
            return candidate
    return "unknown"


async def collect_llm_prevote(room: GameRoom, agent) -> None:
    gi = room.game_instance
    player = agent.player
    candidates = [candidate.player.name for candidate in _meeting_voters(gi)] + ["I do not know"]
    room.meeting_thinking_players.add(player.name)
    started_at = time.perf_counter()
    print(f"[AI pre-vote] request started for {player.name} (meeting {gi.meeting_number})", flush=True)
    try:
        response = await asyncio.wait_for(
            agent.choose_private_vote(gi.timestep, candidates, "Private pre-discussion vote"),
            timeout=120.0,
        )
        choice = _parse_llm_choice(response, candidates)
        print(
            f"[AI pre-vote] response received from {player.name} after "
            f"{time.perf_counter() - started_at:.1f}s: {choice}",
            flush=True,
        )
    except asyncio.CancelledError:
        print(
            f"[AI pre-vote] request cancelled for {player.name} after "
            f"{time.perf_counter() - started_at:.1f}s",
            flush=True,
        )
        raise
    except Exception as error:
        print(
            f"[AI pre-vote] request failed for {player.name} after "
            f"{time.perf_counter() - started_at:.1f}s: {error}",
            flush=True,
        )
        choice = "unknown"
    finally:
        room.meeting_thinking_players.discard(player.name)
    if player.name in room.pre_votes or not room.meeting_prevote_open:
        return
    target = _find_vote_target(gi, choice, actor=player)
    room.pre_votes[player.name] = target.name if target else "unknown"
    record_system_event(
        gi,
        "PRE_VOTE",
        {"choice": room.pre_votes[player.name], "private": True},
        status="private",
        actor=player,
        target=target,
        action_name="PRE_VOTE",
    )


async def prepare_llm_final_vote(room: GameRoom, agent) -> None:
    gi = room.game_instance
    player = agent.player
    candidates = [
        candidate.player.name
        for candidate in _meeting_voters(gi)
        if candidate.player is not player
    ] + ["Skip vote"]
    room.meeting_thinking_players.add(player.name)
    started_at = time.perf_counter()
    print(f"[AI final vote] request started for {player.name} (meeting {gi.meeting_number})", flush=True)
    try:
        response = await asyncio.wait_for(
            agent.choose_private_vote(gi.timestep, candidates, "Final vote"),
            timeout=120.0,
        )
        choice = _parse_llm_choice(response, candidates)
        print(
            f"[AI final vote] response received from {player.name} after "
            f"{time.perf_counter() - started_at:.1f}s: {choice}",
            flush=True,
        )
    except asyncio.CancelledError:
        print(
            f"[AI final vote] request cancelled for {player.name} after "
            f"{time.perf_counter() - started_at:.1f}s",
            flush=True,
        )
        raise
    except Exception as error:
        print(
            f"[AI final vote] request failed for {player.name} after "
            f"{time.perf_counter() - started_at:.1f}s: {error}",
            flush=True,
        )
        choice = "unknown"
    target = _find_vote_target(gi, choice, allow_self=False, actor=player)
    agent.queued_action = Vote(current_location=player.location, other_player=target)
    record_system_event(
        gi,
        "AI_FINAL_VOTE_SELECTED",
        {"choice": target.name if target else "none", "private": True},
        status="private",
        actor=player,
        target=target,
        action_name="VOTE",
    )
    influence_options = [candidate.player.name for candidate in _meeting_voters(gi)] + ["No one"]
    influence_started_at = time.perf_counter()
    print(f"[AI vote influence] request started for {player.name} (meeting {gi.meeting_number})", flush=True)
    try:
        influence_response = await asyncio.wait_for(
            agent.choose_private_influences(gi.timestep, influence_options),
            timeout=120.0,
        )
        response_text = str(influence_response).lower()
        influences = [
            candidate
            for candidate in influence_options[:-1]
            if candidate.lower() in response_text
        ]
        if "no one" in response_text or not influences:
            influences = ["No one"]
        print(
            f"[AI vote influence] response received from {player.name} after "
            f"{time.perf_counter() - influence_started_at:.1f}s: {', '.join(influences)}",
            flush=True,
        )
    except asyncio.CancelledError:
        print(
            f"[AI vote influence] request cancelled for {player.name} after "
            f"{time.perf_counter() - influence_started_at:.1f}s",
            flush=True,
        )
        raise
    except Exception as error:
        print(
            f"[AI vote influence] request failed for {player.name} after "
            f"{time.perf_counter() - influence_started_at:.1f}s: {error}",
            flush=True,
        )
        influences = ["No one"]
    finally:
        room.meeting_thinking_players.discard(player.name)
    room.vote_influences[player.name] = influences
    record_system_event(
        gi,
        "VOTE_INFLUENCE",
        {"influences": influences, "private": True},
        status="private",
        actor=player,
        action_name="VOTE_INFLUENCE",
    )


async def generate_llm_meeting_speech(room: GameRoom, agent) -> None:
    gi = room.game_instance
    player = agent.player
    if not gi or room.meeting_voting_open or not getattr(player, "is_alive", True):
        room.meeting_thinking_players.discard(player.name)
        return

    await broadcast_state(room)
    try:
        # A Speak action stores its chosen text. Rebuild the available actions so
        # this request receives a fresh `SPEAK: ...` option, not its last reply.
        gi.check_actions()
        action = await asyncio.wait_for(agent.choose_action(gi.timestep), timeout=120.0)
        if (
            room.game_instance is gi
            and not room.meeting_voting_open
            and time.time() < room.meeting_discussion_deadline
            and getattr(player, "is_alive", True)
            and getattr(action, "name", None) == "SPEAK"
            and getattr(action, "message", "").strip()
            and not _is_silence_message(getattr(action, "message", ""))
        ):
            gi.record_activity(player, action)
            room.meeting_last_message_at = time.time()
            schedule_llm_speech_rolls(room)
        else:
            print(f"Meeting reply from {player.name} was unavailable or expired.")
    except asyncio.TimeoutError:
        print(f"Meeting speech generation timed out for {player.name}.")
    except asyncio.CancelledError:
        raise
    except Exception as error:
        print(f"Meeting speech generation failed for {player.name}: {error}")
    finally:
        room.meeting_thinking_players.discard(player.name)
        await broadcast_state(room)


# Run a shared discussion window, then use the normal engine only for voting.
async def run_meeting_step(room: GameRoom) -> None:
    stop_realtime_task_phase(room)

    gi = room.game_instance
    gi.meeting_number = getattr(gi, "meeting_number", 0) + 1
    room.voting_deadline_set = False
    room.meeting_voting_open = False
    room.meeting_prevote_open = True
    room.meeting_discussion_started = False
    room.meeting_final_vote_preparing = False
    room.pre_votes.clear()
    room.pending_final_votes.clear()
    room.vote_influences.clear()
    gi.external_discussion_complete = False
    room.meeting_discussion_deadline = 0
    # The private pre-vote uses the same bounded response window as the final vote.
    room.turn_deadline = time.time() + MEETING_VOTING_SECONDS
    room.meeting_last_message_at = time.time()
    room.meeting_last_idle_roll_at = room.meeting_last_message_at
    # A meeting clears the previous task phase's kill cooldown.
    room.kill_cooldown_deadlines.clear()
    for player in gi.players:
        if player.identity == "Impostor":
            player.kill_cooldown = 0
    # Keep SPEAK available while the server manages the shared discussion window.
    gi.discussion_rounds_left = gi.game_config["discussion_rounds"]
    # Meetings are global conversations: placing everyone in Cafeteria means the
    # engine's real-time message routing reaches every other living participant.
    for player in gi.players:
        if is_connected_player(player):
            player.location = "Cafeteria"
    gi.update_map()
    gi.check_actions()
    await broadcast_state(room)

    ai_prevote_agents = [
        agent for agent in _meeting_voters(gi)
        if not isinstance(agent, WebPlayerAgent)
    ]
    print(
        "[AI pre-vote] scheduling "
        f"{len(ai_prevote_agents)} request(s): "
        f"{', '.join(agent.player.name for agent in ai_prevote_agents) or 'none'}",
        flush=True,
    )
    ai_prevote_tasks = [
        asyncio.create_task(collect_llm_prevote(room, agent))
        for agent in ai_prevote_agents
    ]

    async def broadcast_loop():
        while (
            not room.game_finished
            and room.game_instance
            and str(room.game_instance.current_phase).lower() == "meeting"
        ):
            now = time.time()
            if (
                room.meeting_discussion_started
                and not room.meeting_voting_open
                and now - room.meeting_last_message_at >= 5
                and now - room.meeting_last_idle_roll_at >= 5
            ):
                room.meeting_last_idle_roll_at = now
                schedule_llm_speech_rolls(room)
            if room.meeting_prevote_open and room.turn_deadline and now >= room.turn_deadline:
                for agent in _meeting_voters(gi):
                    player = agent.player
                    if player.name in room.pre_votes:
                        continue
                    room.pre_votes[player.name] = "unknown"
                    record_system_event(
                        gi,
                        "PRE_VOTE",
                        {"choice": "unknown", "private": True, "timed_out": True},
                        status="private",
                        actor=player,
                        action_name="PRE_VOTE",
                    )
                room.turn_deadline = 0
            if room.meeting_voting_open and room.turn_deadline and time.time() >= room.turn_deadline:
                for idx in room.sessions.values():
                    agent = gi.agents[idx]
                    if (
                        isinstance(agent, WebPlayerAgent)
                        and agent.queued_action is None
                        and getattr(agent.player, "is_alive", True)
                        and is_connected_player(agent.player)
                    ):
                        selected_choice = room.pending_final_votes.get(agent.player.name, "none")
                        selected_target = _find_vote_target(
                            gi,
                            selected_choice,
                            allow_self=False,
                            actor=agent.player,
                        )
                        room.pending_final_votes[agent.player.name] = selected_target.name if selected_target else "none"
                        room.vote_influences[agent.player.name] = ["No one"]
                        agent.queued_action = Vote(current_location=agent.player.location, other_player=selected_target)
                        if selected_choice == "none":
                            log_human_action(gi, agent.player, "TIMEOUT_VOTE", {"target": "none"})
                        record_system_event(
                            gi,
                            "VOTE_INFLUENCE",
                            {"influences": ["No one"], "private": True, "timed_out": True},
                            status="private",
                            actor=agent.player,
                            action_name="VOTE_INFLUENCE",
                        )
                room.turn_deadline = 0
            await broadcast_state(room)
            await asyncio.sleep(1.0)

    broadcast_task = asyncio.create_task(broadcast_loop())
    try:
        while (
            not room.game_finished
            and str(gi.current_phase).lower() == "meeting"
            and not all(agent.player.name in room.pre_votes for agent in _meeting_voters(gi))
        ):
            await asyncio.sleep(0.25)

        if not room.game_finished and str(gi.current_phase).lower() == "meeting":
            for task in ai_prevote_tasks:
                if not task.done():
                    task.cancel()
            pre_vote_results = await asyncio.gather(*ai_prevote_tasks, return_exceptions=True)
            for agent, result in zip(ai_prevote_agents, pre_vote_results):
                if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):
                    print(
                        f"[AI pre-vote] task failed for {agent.player.name}: {result}",
                        flush=True,
                    )
            room.meeting_prevote_open = False
            room.meeting_discussion_started = True
            room.meeting_discussion_deadline = time.time() + MEETING_DISCUSSION_SECONDS
            room.turn_deadline = room.meeting_discussion_deadline
            reporter = get_meeting_reporter(gi)
            reporter_agent = next((agent for agent in gi.agents if agent.player is reporter), None)
            if (
                reporter_agent
                and not isinstance(reporter_agent, WebPlayerAgent)
                and getattr(reporter_agent.player, "is_alive", True)
            ):
                start_llm_meeting_speech(room, reporter_agent, "meeting reporter")
            await broadcast_state(room)

        while (
            not room.game_finished
            and str(gi.current_phase).lower() == "meeting"
            and time.time() < room.meeting_discussion_deadline
        ):
            await asyncio.sleep(0.25)

        if not room.game_finished and str(gi.current_phase).lower() == "meeting":
            cancel_meeting_llm_tasks(room)
            room.meeting_final_vote_preparing = True
            await broadcast_state(room)
            await asyncio.gather(
                *[
                    prepare_llm_final_vote(room, agent)
                    for agent in _meeting_voters(gi)
                    if not isinstance(agent, WebPlayerAgent)
                ],
                return_exceptions=True,
            )
            room.meeting_final_vote_preparing = False
            room.meeting_voting_open = True
            room.voting_deadline_set = True
            room.turn_deadline = time.time() + MEETING_VOTING_SECONDS
            gi.discussion_rounds_left = 0
            gi.external_discussion_complete = True
            await broadcast_state(room)

            # The final vote is not complete until every participant has also
            # recorded its influence attribution (or the vote window expires).
            # Only then let the engine tally and potentially end the game.
            while (
                not room.game_finished
                and str(gi.current_phase).lower() == "meeting"
                and not all(agent.player.name in room.vote_influences for agent in _meeting_voters(gi))
            ):
                await asyncio.sleep(0.25)

            if not room.game_finished and str(gi.current_phase).lower() == "meeting":
                await gi.game_step()
    finally:
        cancel_meeting_llm_tasks(room)
        broadcast_task.cancel()
        await asyncio.gather(broadcast_task, return_exceptions=True)
        room.meeting_running = False
    # Mark ejected player as reported so they don't appear as a fresh corpse next task phase
    if room.game_instance:
        vote = get_latest_vote_result(room.game_instance)
        if vote and vote.get("ejected"):
            ejected_color = vote["ejected"]
            for player in room.game_instance.players:
                if ejected_color in player.name.lower() and not getattr(player, 'is_alive', True):
                    player.reported_death = True
    if not room.game_finished and room.game_instance and str(room.game_instance.current_phase).lower() == "task":
        start_realtime_task_phase(room)
    await broadcast_state(room)  # Final broadcast after meeting ends

# --- API ENDPOINTS ---
# WebSocket endpoint for pushing game state updates to client
# Expects a session token query param to identify which room and player is connecting
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(...)) -> None:
    room = get_room(token)
    if not room:
        await websocket.accept()
        await websocket.close(code=4003)  # 4003 = stale/invalid session
        return

    # Validated, accept the connection and save websocket object in dict    
    await websocket.accept()
    room.connections[token] = websocket

    # Send current state immediately on connect so the client is immediately up to date
    if room.game_instance:
        await broadcast_state(room)

    # Event loop
    # We don't expect to receive any msgs, but kept open in case
    try:
        while True:
            await websocket.receive_text()

    # Handles leavers
    except WebSocketDisconnect:
        room.connections.pop(token, None)
        token_to_room.pop(token, None)
        gi = room.game_instance
        if gi and room.status == "active":
            mark_active_player_disconnected(room, token)
            await broadcast_state(room)
        elif room.status == "open" and token != room.host_token:
            room.sessions.pop(token, None)
            await broadcast_lobby(room)
        elif room.status == "open" and token == room.host_token:
            room_code = next((code for code, candidate in games.items() if candidate is room), None)
            if room.lobby_fill_task and not room.lobby_fill_task.done():
                room.lobby_fill_task.cancel()
            for t in list(room.sessions.keys()):
                token_to_room.pop(t, None)
            games.pop(room_code, None)
            await broadcast_lobby(room, event="room_closed")

# Index
@app.get("/")
async def serve_game() -> FileResponse:
    return FileResponse(game_template_path)


@app.get("/map-editor")
async def serve_map_editor() -> FileResponse:
    return FileResponse(map_editor_template_path)


def build_waiting_room_response(room: GameRoom, token: str, player_idx: int, is_host: bool) -> dict:
    gi = room.game_instance
    agent = gi.agents[player_idx]
    color = agent.player.name.split()[-1].lower()
    role = agent.player.__class__.__name__
    return {
        "token": token,
        "code": next((code for code, candidate in games.items() if candidate is room), ""),
        "role": role,
        "color": color,
        "current_room": agent.player.location,
        "timestep": gi.timestep,
        "roster": get_roster(gi.agents, room.ai_filled_slots),
        "lobby_seconds_left": get_lobby_seconds_left(room),
        "filled_slots": get_filled_slot_count(room),
        "total_slots": room.total_slots,
        "is_host": is_host,
        "room_status": room.status,
    }


def choose_open_room() -> GameRoom | None:
    open_rooms = [
        room for room in games.values()
        if room.status == "open" and get_next_open_slot(room) is not None
    ]
    if not open_rooms:
        return None
    return max(open_rooms, key=lambda room: get_filled_slot_count(room))


def create_room(selected_config, consent_token: object) -> tuple[str, GameRoom]:
    consume_consent_token(consent_token)
    total_slots = selected_config.get("num_players", 5)
    host_token = str(uuid4())

    game_id = f"web_{uuid4().hex}"
    realtime_config = build_realtime_game_config(selected_config)
    gi = AmongUs(
        game_config=realtime_config,
        agent_config=build_agent_config(),
        game_index=game_id,
    )
    gi.game_id = game_id
    gi.meeting_number = 0
    gi.record_game_action = record_engine_action
    gi.record_game_system_event = record_system_event
    gi.initialize_game()
    gi.agents[0] = WebPlayerAgent(gi.players[0])
    host_agent = gi.agents[0]
    host_color = host_agent.player.name.split()[-1].lower()
    host_agent.player.name = host_color.capitalize()
    gi.game_phase = "staging"

    code = generate_room_code()
    while code in games:
        code = generate_room_code()

    room = GameRoom(
        size_config=selected_config,
        total_slots=total_slots,
        host_token=host_token,
        host_color=host_color,
    )
    room.game_instance = gi
    room.game_id = game_id
    room.code = code
    room.sessions[host_token] = 0
    room.consented_tokens.add(host_token)
    room.consented_at_by_slot[0] = datetime.now(timezone.utc).isoformat()
    games[code] = room
    token_to_room[host_token] = code
    start_lobby_countdown_if_ready(room)
    return host_token, room


async def add_human_to_room(room: GameRoom, player_idx: int, consent_token: object) -> tuple[str, dict]:
    consume_consent_token(consent_token)
    gi = room.game_instance
    gi.agents[player_idx] = WebPlayerAgent(gi.players[player_idx])
    human_agent = gi.agents[player_idx]
    human_color = human_agent.player.name.split()[-1].lower()
    human_agent.player.name = human_color.capitalize()

    token = str(uuid4())
    room.sessions[token] = player_idx
    room.consented_tokens.add(token)
    room.consented_at_by_slot[player_idx] = datetime.now(timezone.utc).isoformat()
    token_to_room[token] = next((code for code, candidate in games.items() if candidate is room), "")

    start_lobby_countdown_if_ready(room)
    await broadcast_lobby(room)
    if is_room_full(room):
        await activate_room(room, "Lobby filled. Starting game.")

    return token, build_waiting_room_response(room, token, player_idx, is_host=False)


@app.post("/api/consent")
async def record_consent() -> dict:
    now = time.time()
    for token, issued_at in list(consent_tokens.items()):
        if now - issued_at > CONSENT_TOKEN_TTL_SECONDS:
            consent_tokens.pop(token, None)
    token = str(uuid4())
    consent_tokens[token] = now
    return {"consent_token": token}


@app.post("/api/matchmake")
async def matchmake_game(request: Request) -> dict:
    data = await request.json()
    setup_log_directory()
    init_db()

    room = choose_open_room()
    if room:
        player_idx = get_next_open_slot(room)
        if player_idx is not None:
            _, response = await add_human_to_room(room, player_idx, data.get("consent_token"))
            return response

    selected_config = get_game_config(data.get("size"))
    host_token, room = create_room(selected_config, data.get("consent_token"))
    return build_waiting_room_response(room, host_token, 0, is_host=True)

# Receive player color from frontend, initiate global game instance, and return state to session
@app.post("/api/host")
async def host_game(request: Request) -> dict:
    data = await request.json()

    setup_log_directory()
    init_db() # Okay to do this on every game startup
    selected_config = get_game_config(data.get("size"))
    host_token, room = create_room(selected_config, data.get("consent_token"))
    return build_waiting_room_response(room, host_token, 0, is_host=True)

# Join an existing open room by claiming the next unclaimed agent slot
@app.post("/api/join")
async def join_game(request: Request) -> dict: # Expect code from the request
    data = await request.json()
    code = data.get("code", "").upper().strip()

    if not code or code not in games:
        return {"status": "error", "message": "Room not found"}

    room = games[code] # grab specific session from the code

    if room.status != "open":
        return {"status": "error", "message": "Game already started"}

    # Join the game
    player_idx = get_next_open_slot(room)
    if player_idx is None:
        return {"status": "error", "message": "Game is full"}

    _, response = await add_human_to_room(room, player_idx, data.get("consent_token"))
    return response

# Returns all open rooms for the join screen on frontend
@app.get("/api/lobbies")
async def list_lobbies() -> dict:
    open_rooms = []
    for code, room in games.items():
        if room.status != "open":
            continue
        open_rooms.append({
            "code": code,
            "host_color": room.host_color,
            "human_count": get_filled_slot_count(room),
            "total_slots": room.total_slots,
            "lobby_seconds_left": get_lobby_seconds_left(room),
        })
    return {"lobbies": open_rooms}

# Send response to start game
@app.post("/api/start")
async def start_game(x_player_token: str = Header(...)) -> dict:
    room = get_room(x_player_token)
    if not room or not room.game_instance:
        return {"status": "error", "message": "Room not found"}
    if x_player_token != room.host_token:
        return {"status": "error", "message": "Only the host can start the game"}
    if not is_room_full(room):
        return {"status": "error", "message": "Game must be full before starting"}

    await activate_room(room, "Host started the game.")

    return {"status": "success", "phase": room.game_instance.game_phase}

# Iterates through all agents and returns list of various stats for frontend UI rendering
@app.get("/api/player-states")
async def get_map_state(x_player_token: str = Header(...)):
    room = get_room(x_player_token)
    if not room or not room.game_instance:
        return {"error": "Game not initialized"}
    gi = room.game_instance

    return {
        # name, color, location, is_alive, reported_death, identity
        "players": [
            format_realtime_player_data(room, agent.player)
            for agent in gi.agents
            if is_connected_player(agent.player)
        ]
    }

# Returns everything the frontend needs to render the human player's current room view
# Location, phase, adjacent rooms, available tasks, and other players present in current room
@app.get("/api/room-context")
async def get_room_context(x_player_token: str = Header(...)):
    room = get_room(x_player_token)
    if not room or not room.game_instance:
        return {"error": "Game not initialized"}
    gi = room.game_instance

    agent = get_human_agent(x_player_token)
    if not agent:
        return {"error": "No human agent found"}
    player = agent.player
    if not is_connected_player(player):
        return {"error": "Player disconnected"}
    current_room = player.location

    # Only include tasks the player hasn't finished yet
    # Has progress fraction for multi-step tasks
    all_incomplete = [task for task in player.tasks if not task.check_completion()]

    # Tasks left to do. Each task has a specific assigned location
    personal_tasks = [
        {
            "name": task.name,
            "location": task.location,
            "max_duration": task.max_duration,
            "steps_done": task.max_duration - task.duration,
        }
        for task in all_incomplete
    ]

    room_task_statuses = [
        {
            "name": task.name,
            "location": task.location,
            "completed": task.check_completion(),
            "max_duration": task.max_duration,
            "steps_done": task.max_duration - task.duration,
        }
        for task in player.tasks
        if task.location == current_room
    ]

    # Map each task name to its specific assigned room
    task_locations = {task["name"]: task["location"] for task in personal_tasks}

    # Build player list visible in this room from the viewer's perspective
    is_viewer_alive = getattr(player, 'is_alive', True)
    if is_viewer_alive:
        # Alive players see only alive players + unreported bodies at their body_location
        others_in_room = [
            format_player_data(a.player)
            for a in gi.agents
            if is_connected_player(a.player)
            and a.player.location == current_room
            and a != agent
            and a.player.is_alive
        ]
        # Add unreported bodies in room
        for a in gi.agents:
            body_loc = getattr(a.player, 'body_location', None)
            if (is_connected_player(a.player)
                    and not a.player.is_alive
                    and not getattr(a.player, 'reported_death', False)
                    and body_loc == current_room):
                others_in_room.append(format_player_data(a.player))
    else:
        # Ghosts see all players at their actual location
        others_in_room = [
            format_player_data(a.player)
            for a in gi.agents
            if is_connected_player(a.player)
            and a.player.location == current_room
            and a != agent
        ]

    # Check if the player can call an emergency meeting: alive, in cafeteria, during task phase, and meetings remaining
    is_alive = getattr(player, 'is_alive', True)
    can_call_meeting = (
        is_alive
        and is_connected_player(player)
        and gi.current_phase == "task"
        and current_room == "Cafeteria"
        and gi.button_num < gi.game_config["max_num_buttons"]
    )
    kill_cooldown = _action_cooldown_seconds_left(room, player, "KILL")
    can_kill = (
        is_alive
        and is_connected_player(player)
        and player.identity == "Impostor"
        and gi.current_phase == "task"
        and kill_cooldown == 0
    )

    return {
        "current_room": current_room,
        "phase": str(gi.current_phase),
        "adjacent": skeld.get_adjacent_rooms(current_room),
        "tasks_in_room": room_data.get(current_room, {}).get("tasks", []),
        "personal_tasks": personal_tasks,
        "room_task_statuses": room_task_statuses,
        "task_locations": task_locations,
        "timestep": gi.timestep,
        "players_in_room": others_in_room,
        "is_alive": is_alive,
        "can_call_meeting": can_call_meeting,
        "can_kill": can_kill,
        "kill_cooldown_seconds": kill_cooldown,
    }

# Handles moving, trigers AI turns, and generates movement observations
@app.post("/api/move")
async def move_player(request: Request, x_player_token: str = Header(...)) -> dict:
    room = get_room(x_player_token)
    gi = room.game_instance
    data = await request.json()
    new_room = data.get("destination")

    human_agent = get_human_agent(x_player_token)
    player = human_agent.player
    is_alive = getattr(player, 'is_alive', True)

    initial_neighbors = get_players_in_room_except_human(gi, player.location, player)
    old_room = player.location

    await execute_realtime_task_action(
        room,
        human_agent,
        MoveTo(current_location=old_room, new_location=new_room),
        human_submission=(
            "MOVE",
            {"from": old_room, "to": new_room},
        ),
    )

    # Generate movement observations (X was seen leaving towards Y)
    observations = generate_room_observations(gi, initial_neighbors, old_room) if is_alive else []
    vent_observations = generate_vent_observations(gi.camera_record, initial_neighbors, old_room) if is_alive else []
    vent_observations += generate_kill_observations(gi.camera_record, initial_neighbors) if is_alive else []
    return {
        "status": "success",
        "current_room": player.location,
        "timestep": gi.timestep,
        "observations": observations,
        "vent_observations": vent_observations,
        "is_alive" : is_alive
    }

# Start a timed human task. Completion is accepted only after the full duration.
@app.post("/api/start-task")
async def start_task(request: Request, x_player_token: str = Header(...)) -> dict:
    room = get_room(x_player_token)
    if not room or not room.game_instance:
        raise HTTPException(status_code=404, detail="No active game session")
    gi = room.game_instance
    data = await request.json()
    task_name = data.get("task")
    human_agent = get_human_agent(x_player_token)
    player = human_agent.player

    if not getattr(player, "is_alive", True):
        raise HTTPException(status_code=403, detail="Ghosts cannot complete tasks.")
    if str(gi.current_phase).lower() != "task":
        raise HTTPException(status_code=400, detail="Tasks are only available during the map phase.")

    task = next(
        (
            candidate
            for candidate in player.tasks
            if candidate.name == task_name
            and not candidate.check_completion()
            and candidate.location == player.location
        ),
        None,
    )
    if task is None:
        raise HTTPException(status_code=400, detail="That task is no longer available here.")

    room.active_human_tasks[player.name] = {
        "task_name": task.name,
        "location": player.location,
        "started_at": time.monotonic(),
    }
    room.active_player_tasks[player.name] = {
        "task_name": task.name,
        "location": player.location,
        "started_at": time.monotonic(),
    }
    _record_human_map_action(room, player)
    record_system_event(
        gi,
        "TASK_STARTED",
        {"task": task.name, "location": player.location, "duration_seconds": TASK_DURATION_SECONDS},
        status="started",
        actor=player,
        action_name="COMPLETE TASK",
    )
    _route_task_started_observation(gi, player, task.name)
    await broadcast_state(room)
    return {"status": "started", "task": task.name, "duration_seconds": TASK_DURATION_SECONDS}


# Complete a task after its human-visible timer reaches zero.
@app.post("/api/do-task")
async def do_task(request: Request, x_player_token: str = Header(...))  -> dict:
    room = get_room(x_player_token)
    gi = room.game_instance
    data = await request.json()
    task_name = data.get("task")

    human_agent = get_human_agent(x_player_token)
    player = human_agent.player
    is_alive = getattr(human_agent.player, 'is_alive', True)

    active_task = room.active_human_tasks.get(player.name)
    if not active_task or active_task["task_name"] != task_name:
        raise HTTPException(status_code=400, detail="Start the task before completing it.")
    if active_task["location"] != player.location:
        room.active_human_tasks.pop(player.name, None)
        room.active_player_tasks.pop(player.name, None)
        raise HTTPException(status_code=400, detail="You left the task before it was finished.")
    elapsed = time.monotonic() - active_task["started_at"]
    if elapsed < TASK_DURATION_SECONDS:
        raise HTTPException(status_code=400, detail="That task is still in progress.")

    initial_neighbors = get_players_in_room_except_human(gi, player.location, player)
    task_to_complete = next((t for t in player.tasks if t.name == task_name and not t.check_completion() and t.location == player.location), None)

    if not task_to_complete:
        room.active_human_tasks.pop(player.name, None)
        room.active_player_tasks.pop(player.name, None)
        return {"status": "error", "message": "Error completing task", "observations": []}

    task_room = player.location
    room.active_player_tasks.pop(player.name, None)

    await execute_realtime_task_action(
        room,
        human_agent,
        CompleteTask(current_location=player.location, task=task_to_complete),
        human_submission=("COMPLETE_TASK", {"task": task_name, "location": task_room}),
        track_human_rate=False,
    )
    room.active_human_tasks.pop(player.name, None)

    # Build progress message for multi-step tasks.
    # If task is complete, just say completed. If not, show steps done out of total.
    steps_done = task_to_complete.max_duration - task_to_complete.duration
    max_dur = task_to_complete.max_duration
    if task_to_complete.check_completion():
        msg = f"You completed {task_name}!"
        if max_dur > 1:
            msg = f"You completed {task_name}! ({max_dur}/{max_dur})"
    else:
        msg = f"Working on {task_name}... ({steps_done}/{max_dur})"

    observations = generate_room_observations(gi, initial_neighbors, player.location) if is_alive else []
    vent_observations = generate_vent_observations(gi.camera_record, initial_neighbors, task_room) if is_alive else []
    vent_observations += generate_kill_observations(gi.camera_record, initial_neighbors) if is_alive else []
    return {
        "status": "success",
        "message": msg,
        "timestep": gi.timestep,
        "observations": observations,
        "vent_observations": vent_observations,
        "is_alive": is_alive
    }

# Endpoint for reporting dead body
@app.post("/api/report")
async def report_body(request: Request, x_player_token: str = Header(...)) -> dict:
    room = get_room(x_player_token)
    if not room or not room.game_instance:
        return {"error": "Game not initialized"}
    gi = room.game_instance

    human_agent = get_human_agent(x_player_token)
    player = human_agent.player
    is_alive = getattr(player, 'is_alive', True)

    # Guard for ghosts
    if not is_alive:
        return {
            "status": "error",
            "message": "Ghosts cannot report bodies!",
            "timestep": gi.timestep,
            "is_alive": is_alive
        }

    # Find unreported corpse at this location using body_location
    dead_player = next((
        p for p in gi.players
        if is_connected_player(p)
        and not p.is_alive
        and not getattr(p, 'reported_death', False)
        and getattr(p, 'body_location', None) == player.location
    ), None)
    dead_name = get_clean_name(dead_player) if dead_player else "Unknown"

    # Important: Clear any messages from pre-existing meetings
    if hasattr(gi, 'meeting_messages'):
        gi.meeting_messages = []
    await execute_realtime_task_action(
        room,
        human_agent,
        CallMeeting(current_location=player.location),
        human_submission=("REPORT", {"body": dead_name, "location": player.location}),
    )

    return {
        "status": "success",
        "message": f"🚨 {human_agent.player.name.split(':')[-1].strip().capitalize()} reported {dead_name}'s body!",
        "timestep": gi.timestep,
        "phase": gi.current_phase,
        "is_alive": is_alive
    }

# Similar to /report endpoint but for calling meeting without reporting a body. Only available in cafeteria and if meetings remain.
@app.post("/api/call-meeting")
async def call_meeting(request: Request, x_player_token: str = Header(...)) -> dict:
    room = get_room(x_player_token)
    if not room or not room.game_instance:
        return {"error": "Game not initialized"}
    gi = room.game_instance

    human_agent = get_human_agent(x_player_token)
    player = human_agent.player
    is_alive = getattr(player, 'is_alive', True)

    if not is_alive:
        return {"status": "error", "message": "Ghosts cannot call meetings!"}
    if player.location != "Cafeteria":
        return {"status": "error", "message": "Emergency can only be called from the Cafeteria!"}
    if gi.button_num >= gi.game_config["max_num_buttons"]:
        return {"status": "error", "message": "No emergency meetings remaining!"}

    if hasattr(gi, 'meeting_messages'):
        gi.meeting_messages = []
    await execute_realtime_task_action(
        room,
        human_agent,
        CallMeeting(current_location=player.location),
        human_submission=("CALL_MEETING", {"location": player.location}),
    )

    return {
        "status": "success",
        "message": f"🚨 {human_agent.player.name.split(':')[-1].strip().capitalize()} called an emergency meeting!",
        "timestep": gi.timestep,
        "phase": gi.current_phase,
        "is_alive": is_alive,
    }

# Handles kill action and generates kill observations
@app.post("/api/kill")
async def kill_player(request: Request, x_player_token: str = Header(...)) -> dict:
    room = get_room(x_player_token)
    gi = room.game_instance
    data = await request.json()
    target_color = data.get("target")

    human_agent = get_human_agent(x_player_token)
    if not human_agent:
        return {"status": "error", "message": "No human agent found"}
    human_player = human_agent.player
    is_alive = getattr(human_player, 'is_alive', True)

    # Guard for Ghosts
    if not is_alive:
        return {
            "status": "error",
            "message": "Ghosts cannot kill others!",
            "timestep": gi.timestep,
            "is_alive": is_alive
        }

    if "Impostor" not in human_player.__class__.__name__:
        raise HTTPException(status_code=403, detail="Only impostors can kill.")
    if str(gi.current_phase).lower() != "task":
        raise HTTPException(status_code=400, detail="Kills are only available during the task phase.")
    if not isinstance(target_color, str):
        raise HTTPException(status_code=400, detail="A kill target is required.")

    # Find target player object by color
    target_player = next((
        player for player in gi.players
        if is_connected_player(player) and target_color.lower() in player.name.lower()
    ), None)

    if not target_player:
        return {
            "status": "error",
            "message": "Error: Target not found.",
            "timestep": gi.timestep,
            "is_alive": is_alive,
        }
    if target_player is human_player or not getattr(target_player, "is_alive", True):
        raise HTTPException(status_code=400, detail="That player cannot be killed.")
    if target_player.location != human_player.location:
        raise HTTPException(status_code=400, detail="Kill targets must be in the same room.")
    kill_cooldown_seconds = _action_cooldown_seconds_left(room, human_player, "KILL")
    if kill_cooldown_seconds:
        raise HTTPException(status_code=400, detail=f"Kill is on cooldown for {kill_cooldown_seconds}s.")

    kill_room = human_player.location
    initial_neighbors = get_players_in_room_except_human(gi, kill_room, human_player)
    await execute_realtime_task_action(
        room,
        human_agent,
        Kill(current_location=kill_room, other_player=target_player),
        human_submission=(
            "KILL",
            {"target": target_color.capitalize(), "location": human_player.location},
        ),
    )

    observations = generate_room_observations(gi, initial_neighbors, kill_room)
    vent_observations = generate_vent_observations(gi.camera_record, initial_neighbors, kill_room)
    vent_observations += generate_kill_observations(gi.camera_record, initial_neighbors)

    return{
        "status": "success",
        "message": f"You killed {target_color.capitalize()}!",
        "kill_event": room.kill_events[-1],
        "timestep": gi.timestep,
        "is_alive": is_alive,
        "observations": observations,
        "vent_observations": vent_observations,
    }

# Endpoint for sending chat messages during meetings
@app.post("/api/typing")
async def set_human_typing(request: Request, x_player_token: str = Header(...)) -> dict:
    room = get_room(x_player_token)
    if not room or not room.game_instance:
        raise HTTPException(status_code=404, detail="No active game session")

    gi = room.game_instance
    agent = get_human_agent(x_player_token)
    player = agent.player
    data = await request.json()
    is_typing = bool(data.get("is_typing"))
    discussion_open = (
        str(gi.current_phase).lower() == "meeting"
        and room.meeting_running
        and not room.meeting_voting_open
        and time.time() < room.meeting_discussion_deadline
        and getattr(player, "is_alive", True)
    )
    if is_typing and discussion_open:
        room.meeting_thinking_players.add(player.name)
    else:
        room.meeting_thinking_players.discard(player.name)
    await broadcast_state(room)
    return {"status": "success"}


@app.post("/api/speak")
async def human_speak(request: Request, x_player_token: str = Header(...)) -> dict:
    room = get_room(x_player_token)
    if not room or not room.game_instance:
        return {"error": "No active game session"}
    gi = room.game_instance

    data = await request.json()
    chat_msg = str(data.get("message", "")).strip()

    human_agent = get_human_agent(x_player_token)
    player = human_agent.player
    is_alive = getattr(player, 'is_alive', True)

    # Guard for Ghosts
    if not is_alive:
        return {
            "status": "error",
            "message": "Ghosts can't talk!",
            "timestep": gi.timestep,
            "is_alive": is_alive
        }
    if (
        str(gi.current_phase).lower() != "meeting"
        or not room.meeting_running
        or room.meeting_voting_open
        or time.time() >= room.meeting_discussion_deadline
    ):
        raise HTTPException(status_code=400, detail="Discussion is closed.")
    if not chat_msg:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    # Shared discussion messages are recorded immediately; they are not queued for
    # the sequential game engine.
    room.meeting_thinking_players.discard(player.name)
    action = Speak(current_location=player.location)
    action.provide_message(chat_msg)
    log_human_action(gi, player, "SPEAK", {"message": chat_msg, "phase": str(gi.current_phase)})
    gi.record_activity(player, action)
    room.meeting_last_message_at = time.time()
    schedule_llm_speech_rolls(room)
    await broadcast_state(room)

    return {
        "status": "success",
        "timestep": gi.timestep,
        "is_alive": True
    }

# Endpoint for advancing to the next discussion phase during meetings.
@app.post("/api/next-step")
async def next_step(x_player_token: str = Header(...)) -> dict:
    room = get_room(x_player_token)
    if not room or not room.game_instance:
        return {"error": "No game"}
    gi = room.game_instance

    current_phase = str(gi.current_phase).lower()
    if current_phase != "meeting":
        return {"status": "not_meeting"}

    await start_meeting_if_needed(room)

    return {"status": "success"}

# Legacy compatibility endpoint. Ghost discussion turns are now skipped by the game engine.
@app.post("/api/set-nudge")
async def set_nudge(x_player_token: str = Header(...)) -> dict:
    return {"status": "ignored", "message": "Ghost turns are skipped automatically."}


@app.post("/api/pre-vote")
async def submit_pre_vote(request: Request, x_player_token: str = Header(...)) -> dict:
    room = get_room(x_player_token)
    gi = room.game_instance
    if not room.meeting_prevote_open or str(gi.current_phase).lower() != "meeting":
        raise HTTPException(status_code=400, detail="The private pre-vote is not open.")
    if room.turn_deadline and time.time() >= room.turn_deadline:
        raise HTTPException(status_code=400, detail="The private pre-vote has ended.")
    agent = get_human_agent(x_player_token)
    player = agent.player
    if not getattr(player, "is_alive", True):
        raise HTTPException(status_code=403, detail="Ghosts cannot cast a pre-vote.")
    if player.name in room.pre_votes:
        raise HTTPException(status_code=400, detail="Your private pre-vote has already been recorded.")

    choice = (await request.json()).get("target", "unknown")
    target = _find_vote_target(gi, choice, actor=player)
    if target is None and str(choice).strip().lower() not in {"unknown", "i do not know", "none"}:
        raise HTTPException(status_code=400, detail="Choose a living player or I do not know.")
    room.pre_votes[player.name] = target.name if target else "unknown"
    record_system_event(
        gi,
        "PRE_VOTE",
        {"choice": room.pre_votes[player.name], "private": True},
        status="private",
        actor=player,
        target=target,
        action_name="PRE_VOTE",
    )
    await broadcast_state(room)
    return {"status": "success"}


# Endpoint for submitting votes during meetings.
# Expects target player color or "none" for skip.
@app.post("/api/vote")
async def handle_vote(request: Request, x_player_token: str = Header(...)) -> dict:
    room = get_room(x_player_token)
    if not room or not room.game_instance:
        raise HTTPException(status_code=404, detail="No active game session")
    if not room.meeting_voting_open:
        raise HTTPException(status_code=400, detail="Voting has not opened yet.")
    gi = room.game_instance
    data = await request.json()
    target_color = data.get("target")
    human_agent = get_human_agent(x_player_token)
    player = human_agent.player

    target_player = None

    if not getattr(player, 'is_alive', True):
        raise HTTPException(status_code=403, detail="Ghosts cannot vote.")
    if player.name in room.pending_final_votes:
        raise HTTPException(status_code=400, detail="Your final vote has already been selected.")

    # Select a vote now; it is queued only after influence attribution is complete.
    if target_color != "none":
        target_player = _find_vote_target(gi, target_color, allow_self=False, actor=player)
        if target_player is None:
            raise HTTPException(status_code=400, detail="Choose a living ship-mate or skip the vote.")

    room.pending_final_votes[player.name] = target_player.name if target_player else "none"
    log_human_action(gi, player, "VOTE", {"target": target_color})
    record_system_event(
        gi,
        "FINAL_VOTE_SELECTED",
        {"choice": room.pending_final_votes[player.name], "private": True},
        status="private",
        actor=player,
        target=target_player,
        action_name="VOTE",
    )
    await broadcast_state(room)

    return {"status": "success", "next": "influence"}


@app.post("/api/vote-influence")
async def submit_vote_influence(request: Request, x_player_token: str = Header(...)) -> dict:
    room = get_room(x_player_token)
    gi = room.game_instance
    if not room.meeting_voting_open:
        raise HTTPException(status_code=400, detail="Voting is not open.")
    human_agent = get_human_agent(x_player_token)
    player = human_agent.player
    if player.name not in room.pending_final_votes:
        raise HTTPException(status_code=400, detail="Select your final vote before identifying influences.")
    if player.name in room.vote_influences:
        raise HTTPException(status_code=400, detail="Your vote influence response has already been recorded.")

    submitted = (await request.json()).get("influences", [])
    if not isinstance(submitted, list):
        raise HTTPException(status_code=400, detail="Influences must be a list.")
    no_one = any(str(value).strip().lower() == "no one" for value in submitted)
    if no_one and len(submitted) != 1:
        raise HTTPException(status_code=400, detail="No one cannot be combined with ship-mates.")
    influences = ["No one"] if no_one else []
    if not no_one:
        for value in submitted:
            influence_player = _find_vote_target(gi, value, actor=player)
            if influence_player is None:
                raise HTTPException(status_code=400, detail="Influences must be living ship-mates.")
            if influence_player.name not in influences:
                influences.append(influence_player.name)
        if not influences:
            influences = ["No one"]

    selected_target = _find_vote_target(gi, room.pending_final_votes[player.name], allow_self=False, actor=player)
    room.vote_influences[player.name] = influences
    human_agent.queued_action = Vote(current_location=player.location, other_player=selected_target)
    record_system_event(
        gi,
        "VOTE_INFLUENCE",
        {"influences": influences, "private": True},
        status="private",
        actor=player,
        action_name="VOTE_INFLUENCE",
    )
    await broadcast_state(room)
    return {"status": "success"}

# 
@app.get("/api/vent-options")
async def get_vent_options(x_player_token: str = Header(...)) -> dict:
    room = get_room(x_player_token)
    human_agent = get_human_agent(x_player_token)

    # Only alive impostors can vent
    is_impostor = "Impostor" in human_agent.player.__class__.__name__
    is_alive = getattr(human_agent.player, 'is_alive', True)

    if not is_impostor or not is_alive:
        return {"can_vent": False, "options": [], "cooldown_seconds": 0}

    cooldown_seconds = _action_cooldown_seconds_left(room, human_agent.player, "VENT")
    if cooldown_seconds:
        return {"can_vent": False, "options": [], "cooldown_seconds": cooldown_seconds}

    current_room = human_agent.player.location

    vent_targets = [
        adj for adj, attr in skeld.ship_map[current_room].items() if attr.get("connection_type") == "vent"
    ]

    return{
        "can_vent": len(vent_targets) > 0,
        "options": vent_targets,
        "cooldown_seconds": 0,
    }

@app.post("/api/vent")
async def perform_vent(request: Request, x_player_token: str = Header(...)):
    room = get_room(x_player_token)
    gi = room.game_instance
    data = await request.json()
    target_room = data.get("destination")

    human_agent = get_human_agent(x_player_token)
    player = human_agent.player
    is_alive = getattr(player, 'is_alive', True)

    # Capture stats before venting for observations
    initial_neighbors = get_players_in_room_except_human(gi, player.location, player)
    old_room = player.location

    # Ghost Guard
    if not is_alive:
        return {
            "status": "error",
            "message": "Ghosts cannot vent!",
            "timestep": gi.timestep,
            "is_alive": False
        }

    cooldown_seconds = _action_cooldown_seconds_left(room, player, "VENT")
    if cooldown_seconds:
        raise HTTPException(status_code=400, detail=f"Vent is on cooldown for {cooldown_seconds}s.")

    await execute_realtime_task_action(
        room,
        human_agent,
        Vent(current_location=player.location, new_location=target_room),
        human_submission=("VENT", {"from": old_room, "to": target_room}),
    )

    observations = generate_room_observations(gi, initial_neighbors, old_room)
    vent_observations = generate_vent_observations(gi.camera_record, initial_neighbors, old_room)
    vent_observations += generate_kill_observations(gi.camera_record, initial_neighbors)
    return {
        "status": "success",
        "current_room": target_room,
        "timestep": gi.timestep,
        "message": f"You vented to {target_room.replace('_', ' ').capitalize()}.",
        "is_alive": is_alive,
        "observations": observations,
        "vent_observations": vent_observations,
    }

if __name__ == "__main__":
    host = os.getenv("UVICORN_HOST", "0.0.0.0")
    port = int(os.getenv("UVICORN_PORT", "8000"))
    uvicorn.run(app, host=host, port=port)
