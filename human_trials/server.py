# server.py
import os
import random
import string
import asyncio
import time
import uvicorn
from uuid import uuid4
from fastapi import FastAPI, Request, Header, WebSocket, WebSocketDisconnect, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from models import skeld, WebPlayerAgent
from amongagents.envs.game import AmongUs
from amongagents.envs.configs.map_config import room_data
from amongagents.envs.configs.game_config import FIVE_MEMBER_GAME, SEVEN_MEMBER_GAME
from amongagents.envs.action import CompleteTask, MoveTo, CallMeeting, Kill, Speak, Vote, Vent
from server_helpers import *
from dotenv import load_dotenv

# --- SETUP ---
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

# Unique ID stamped on every log entry so entries from different server sessions
# can be distinguished even when game_index resets to 0 after a restart.
os.environ['SESSION_ID'] = time.strftime("%Y%m%d_%H%M%S")

# Each GameRoom holds one game's engine, sessions, and WebSocket connections.
class GameRoom:
    def __init__(self, size_config, total_slots, host_token, host_color):
        self.game_instance = None
        self.status = "open" # "open" = joinable, "active" = game running
        self.size_config = size_config
        self.total_slots = total_slots # max num players
        self.host_token = host_token # Only the host can start the game
        self.host_color = host_color # For show in the lobby list
        self.sessions = {} # token -> agent index
        self.connections = {} # token -> WebSocket
        self.step_lock = asyncio.Lock() # To prevent concurrent game_step() calls
        self.meeting_running = False # Guards against double-starting the meeting loop
        self.last_phase = None # Tracks previous phase to detect transitions
        self.meeting_start_step = None # Timestep when current meeting began
        self.discussion_turn_seq = 0 # Increments each time the discussion baton passes to a new human
        self.turn_deadline: float = 0.0 # Unix timestamp when current turn expires
        self.task_timeout_task: asyncio.Task | None = None # Background sleep task for task-phase auto-submit
        self.voting_deadline_set: bool = False # Whether the voting deadline has been set in the current meeting
        self.game_outcome_logged: bool = False

# All active rooms keyed by 4 letter code
games: dict[str, GameRoom] = {}

# Reverse lookup to find a player's room from their session token
token_to_room: dict[str, str] = {}

# Generates 4 letter random key code
def generate_room_code():
    return ''.join(random.choices(string.ascii_uppercase, k=4))

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
current_dir = os.path.dirname(os.path.abspath(__file__))
static_path = os.path.join(current_dir, "static")

# Serve static and asset files 
app.mount("/static", StaticFiles(directory=static_path), name="static")
app.mount("/assets", StaticFiles(directory=os.path.join(current_dir, "assets")), name="assets")

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
    taken = set(room.sessions.values()) # set of taken human player indices
    for i, agent in enumerate(room.game_instance.agents):
        if i not in taken and not isinstance(agent, WebPlayerAgent):
            return i
    return None

# Track meeting phase transitions and per-human turn sequence on the room object.
# Private Helper used in broadcast_state
def _update_meeting_tracking(room: GameRoom, gi, current_phase: str) -> None:
    # Meeting start
    if current_phase == "meeting" and room.last_phase != "meeting":
        room.meeting_start_step = gi.timestep
        room.discussion_turn_seq = 0
        room.turn_deadline = 0
        if room.task_timeout_task and not room.task_timeout_task.done():
            room.task_timeout_task.cancel()
            room.task_timeout_task = None
    # Meeting end
    elif current_phase != "meeting" and room.last_phase == "meeting":
        room.meeting_start_step = None
        room.discussion_turn_seq = 0

    room.last_phase = current_phase

    # Increment turn_seq each time a human's waiting_for_action newly becomes True
    if current_phase == "meeting":
        for agent in gi.agents:
            if isinstance(agent, WebPlayerAgent):
                now_waiting = getattr(agent, 'waiting_for_action', False)
                if now_waiting and not agent._prev_waiting:
                    room.discussion_turn_seq += 1
                    is_ghost = not getattr(agent.player, 'is_alive', True)
                    room.turn_deadline = time.time() + (15 if is_ghost else 60)
                agent._prev_waiting = now_waiting

# Is it a specific player's turn given the current meeting state?
# This accounts for both voting and discussion
def _is_player_turn(agent, is_alive: bool, current_phase: str, can_vote: bool) -> bool:
    if current_phase != "meeting":
        return True  # Task phase: no such thing as a turn
    if can_vote:
        return is_alive  # Only if alive!

    # Discussion Phase: only the human whose choose_action() is currently blocking
    return (isinstance(agent, WebPlayerAgent) and
            getattr(agent, 'waiting_for_action', False))

# Broadcast current game state to all connected players in a room
# This includes player states, phase, timestep, task progress, win status, and meeting context when relevant
async def broadcast_state(room: GameRoom):
    gi = room.game_instance
    if not gi:
        return

    current_phase = str(gi.current_phase).lower()
    can_vote = current_phase == "meeting" and getattr(gi, 'discussion_rounds_left', 0) <= 0
    _update_meeting_tracking(room, gi, current_phase)

    turn_seconds_left = max(0, int(room.turn_deadline - time.time())) if room.turn_deadline > 0 else None
    winner = get_win_message(gi)
    players_data = [format_player_data(agent.player) for agent in gi.agents]
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
        "vote_result": get_latest_vote_result(gi),
        "meeting_messages": parse_meeting_messages(gi, room.meeting_start_step) if current_phase == "meeting" else [],
        "can_vote": can_vote,
        "discussion_turn_seq": room.discussion_turn_seq,
        "turn_seconds_left": turn_seconds_left,
    }

    if payload["winner"] and not room.game_outcome_logged:
        room.game_outcome_logged = True
        log_game_outcome(gi)

    dead = []

    # Iterate through connections and send the current state.
    for token, ws in room.connections.items():
        try:
            idx = room.sessions.get(token)
            agent = gi.agents[idx] if idx is not None else None
            is_alive = getattr(agent.player, 'is_alive', True) if agent else True
            is_my_turn = _is_player_turn(agent, is_alive, current_phase, can_vote)
            killed_by = get_killer_of(gi, agent.player.name) if agent and not is_alive else None
            await ws.send_json({**payload, "is_alive": is_alive, "is_my_turn": is_my_turn, "killed_by": killed_by})
        except Exception:
            # Mark for removal if send fails (client disconnected)
            dead.append(token)
    for t in dead:
        room.connections.pop(t, None)

# Push a lobby event (roster update or game_started) to all waiting players
async def broadcast_lobby(room: GameRoom, event: str = "lobby_update") -> None:
    if not room.game_instance:
        return
    payload = {"type": event, "roster": get_roster(room.game_instance.agents)}
    dead = []
    for token, ws in room.connections.items():
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(token)
    for t in dead:
        room.connections.pop(t, None)


# Queue a stay-in-place null action for every alive human who hasn't acted yet.
# Called before meeting-triggering steps so game_step() doesn't block waiting for idle humans.
def queue_null_actions_for_idle_humans(room: GameRoom) -> None:
    gi = room.game_instance
    for idx in room.sessions.values():
        agent = gi.agents[idx]
        if isinstance(agent, WebPlayerAgent) and agent.queued_action is None:
            if getattr(agent.player, 'is_alive', True):
                agent.queued_action = MoveTo(current_location=agent.player.location, new_location=agent.player.location)

# Returns True if every human has a queued action
def all_humans_ready(room: GameRoom) -> bool:
    gi = room.game_instance
    for idx in room.sessions.values():
        agent = gi.agents[idx]
        if isinstance(agent, WebPlayerAgent) and agent.queued_action is None:
            if getattr(agent.player, 'is_alive', True):
                return False
    return True

# Checks if all humans have queued actions, and if so steps the game and broadcasts state.
# If not, just broadcast current state
async def maybe_step_and_broadcast(room: GameRoom) -> bool:
    if not all_humans_ready(room):
        await broadcast_state(room)
        return False
    async with room.step_lock:
        if not all_humans_ready(room): # Re-check after acquiring lock
            await broadcast_state(room)
            return False
        await room.game_instance.game_step()
    # Reset the timer BEFORE broadcasting so clients receive the fresh 60s deadline
    if room.game_instance and str(room.game_instance.current_phase).lower() == "task":
        start_task_timer(room)
    await broadcast_state(room)
    return True

# Step and broadcast, but only if still in task phase.
# Guards against two players reporting the same body (or double-clicking emergency):
# the second caller waits on the lock, finds the phase already flipped to meeting, and skips.
async def step_and_broadcast(room: GameRoom) -> None:
    async with room.step_lock:
        if str(room.game_instance.current_phase).lower() != "meeting":
            await room.game_instance.game_step()
    await broadcast_state(room)


# 90 seconds per task-phase turn
# Start (or restart) the 90s task-phase turn timer.
# Cancels any running timer and starts a new one.
def start_task_timer(room: GameRoom) -> None:
    if room.task_timeout_task and not room.task_timeout_task.done():
        room.task_timeout_task.cancel()
    room.turn_deadline = time.time() + 90
    room.task_timeout_task = asyncio.create_task(task_phase_timeout(room))

# Auto-submits a null MoveTo (stay in place) for any alive human who hasn't acted after 90s.
async def task_phase_timeout(room: GameRoom) -> None:
    try:
        await asyncio.sleep(90)
    except asyncio.CancelledError:
        return
    gi = room.game_instance
    if not gi or str(gi.current_phase).lower() != "task":
        return
    for idx in room.sessions.values():
        agent = gi.agents[idx]
        if isinstance(agent, WebPlayerAgent) and agent.queued_action is None:
            if getattr(agent.player, 'is_alive', True):
                agent.queued_action = MoveTo(current_location=agent.player.location, new_location=agent.player.location)
                log_human_action(gi, agent.player, "TIMEOUT_TASK", {"location": agent.player.location})
    room.task_timeout_task = None  # Clear before calling maybe_step_and_broadcast to avoid self-cancel
    await maybe_step_and_broadcast(room)


# Run the single long-running meeting game_step as a background task.
# Broadcasts state every second so clients see messages in real time.
async def run_meeting_step(room: GameRoom) -> None:
    # Cancel any leftover task-phase timer
    if room.task_timeout_task and not room.task_timeout_task.done():
        room.task_timeout_task.cancel()
        room.task_timeout_task = None
    room.voting_deadline_set = False

    async def broadcast_loop():
        while room.game_instance and str(room.game_instance.current_phase).lower() == "meeting":
            gi = room.game_instance
            can_vote = getattr(gi, 'discussion_rounds_left', 0) <= 0

            # 60 second deadline when voting opens
            if can_vote and not room.voting_deadline_set:
                room.turn_deadline = time.time() + 60
                room.voting_deadline_set = True

            # Handle afk voting
            if can_vote and room.voting_deadline_set and time.time() > room.turn_deadline:
                for idx in room.sessions.values():
                    agent = gi.agents[idx]
                    if isinstance(agent, WebPlayerAgent) and agent.queued_action is None:
                        if getattr(agent.player, 'is_alive', True):
                            agent.queued_action = Vote(current_location=agent.player.location, other_player=None)
                            log_human_action(gi, agent.player, "TIMEOUT_VOTE", {"target": "none"}) # Write clearly to log
                room.turn_deadline = 0
                break

            # Handle afk discussion turns
            if not can_vote and room.turn_deadline > 0 and time.time() > room.turn_deadline:
                for idx in room.sessions.values():
                    agent = gi.agents[idx]
                    if isinstance(agent, WebPlayerAgent) and agent.queued_action is None:
                        if getattr(agent, 'waiting_for_action', False):
                            action = Speak(current_location=agent.player.location)
                            action.provide_message("...")
                            agent.queued_action = action
                            log_human_action(gi, agent.player, "TIMEOUT_DISCUSS", {"message": "..."}) # Write clearly to log
                room.turn_deadline = 0  # Reset; next human's turn will set a new deadline

            await broadcast_state(room)
            await asyncio.sleep(1.0)

    broadcast_task = asyncio.create_task(broadcast_loop())
    try:
        await room.game_instance.game_step()
    finally:
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
    if room.game_instance and str(room.game_instance.current_phase).lower() == "task":
        start_task_timer(room)
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
        gi = room.game_instance
        if gi and room.status == "active":
            idx = room.sessions.get(token)
            if idx is not None:
                agent = gi.agents[idx]
                log_human_action(gi, agent.player, "disconnect")
        elif room.status == "open" and token == room.host_token:
            room_code = token_to_room.get(token)
            for t in list(room.sessions.keys()):
                token_to_room.pop(t, None)
            games.pop(room_code, None)
            await broadcast_lobby(room, event="room_closed")

# Index
@app.get("/")
async def serve_game() -> FileResponse:
    return FileResponse("templates/game.html")

# Receive player color from frontend, initiate global game instance, and return state to session
@app.post("/api/host")
async def host_game(request: Request) -> dict:
    data = await request.json()

    setup_log_directory()
    init_db() # Okay to do this on every game startup
    selected_config = get_game_config(data.get("size"))
    total_slots = selected_config.get("num_players", 5) # Default to 5
    host_token = str(uuid4()) # Generate a random UUID

    # Initialize engine
    gi = AmongUs(
        game_config=selected_config,
        agent_config={
            "Impostor": "LLM",
            "Crewmate": "LLM",
            "IMPOSTOR_LLM_CHOICES": ["google/gemini-3.5-flash"],
            "CREWMATE_LLM_CHOICES": ["google/gemini-3.5-flash"],    
        }
    )

    gi.initialize_game()

    # Convert Agent 0 (Host) to the human and retrieve attributes
    gi.agents[0] = WebPlayerAgent(gi.players[0])
    host_agent = gi.agents[0]
    host_color = host_agent.player.name.split()[-1].lower()
    host_agent.player.name = host_color.capitalize()
    host_role = host_agent.player.__class__.__name__

    gi.game_phase = "staging"

    # Create room and register host
    code = generate_room_code()
    while code in games:
        code = generate_room_code() # ensures no duplicates

    # Store the entire game state in the room object, keyed by the 4-letter code.
    room = GameRoom(
        size_config=selected_config,
        total_slots=total_slots,
        host_token=host_token,
        host_color=host_color,
    )
    room.game_instance = gi
    room.sessions[host_token] = 0
    games[code] = room # Map room code to game room object
    token_to_room[host_token] = code # Maps hosts UUID to that room code.

    # Contains all info needed to render lobby screen and identify host player for permissions
    return {
        "token": host_token, # Host UUID
        "code": code,
        "role": host_role,
        "color": host_color,
        "current_room": host_agent.player.location,
        "timestep": gi.timestep,
        "roster": get_roster(gi.agents),
        "is_host": True,
    }

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

    # Create new player from an existing AI player
    gi = room.game_instance
    gi.agents[player_idx] = WebPlayerAgent(gi.players[player_idx]) # Turn into WebPlayerAgent
    human_agent = gi.agents[player_idx]
    human_color = human_agent.player.name.split()[-1].lower()
    human_agent.player.name = human_color.capitalize()
    human_role = human_agent.player.__class__.__name__

    token = str(uuid4())
    room.sessions[token] = player_idx
    token_to_room[token] = code

    # Notify all waiting players that someone new joined
    await broadcast_lobby(room)

    return {
        "token": token,
        "code": code,
        "role": human_role,
        "color": human_color,
        "current_room": human_agent.player.location,
        "timestep": gi.timestep,
        "roster": get_roster(gi.agents),
        "is_host": False,
    }

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
            "human_count": len(room.sessions),
            "total_slots": room.total_slots,
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
 
    # Start the game by setting phase to active
    room.status = "active"
    room.game_instance.game_phase = "active"
    room.game_instance.activity_log.append("Host started the game.")

    # Notify all players in the lobby that the game has started
    # This triggers transition to game screen from the lobby screen on the frontend
    await broadcast_lobby(room, event="game_started")
    start_task_timer(room)
    await broadcast_state(room)  # Push initial timer value to all clients

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
        "players": [format_player_data(agent.player) for agent in gi.agents]
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

    # Map each task name to its specific assigned room
    task_locations = {task["name"]: task["location"] for task in personal_tasks}

    # Build player list visible in this room from the viewer's perspective
    is_viewer_alive = getattr(player, 'is_alive', True)
    if is_viewer_alive:
        # Alive players see only alive players + unreported bodies at their body_location
        others_in_room = [
            format_player_data(a.player)
            for a in gi.agents
            if a.player.location == current_room and a != agent and a.player.is_alive
        ]
        # Add unreported bodies in room
        for a in gi.agents:
            body_loc = getattr(a.player, 'body_location', None)
            if (not a.player.is_alive
                    and not getattr(a.player, 'reported_death', False)
                    and body_loc == current_room):
                others_in_room.append(format_player_data(a.player))
    else:
        # Ghosts see all players at their actual location
        others_in_room = [
            format_player_data(a.player)
            for a in gi.agents
            if a.player.location == current_room and a != agent
        ]

    # Check if the player can call an emergency meeting: alive, in cafeteria, during task phase, and meetings remaining
    is_alive = getattr(player, 'is_alive', True)
    can_call_meeting = (
        is_alive
        and gi.current_phase == "task"
        and current_room == "Cafeteria"
        and gi.button_num < gi.game_config["max_num_buttons"]
    )

    return {
        "current_room": current_room,
        "phase": str(gi.current_phase),
        "adjacent": skeld.get_adjacent_rooms(current_room),
        "tasks_in_room": room_data.get(current_room, {}).get("tasks", []),
        "personal_tasks": personal_tasks,
        "task_locations": task_locations,
        "timestep": gi.timestep,
        "players_in_room": others_in_room,
        "is_alive": is_alive,
        "can_call_meeting": can_call_meeting,
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

    human_agent.queued_action = MoveTo(current_location=old_room, new_location=new_room)

    # Await AI agent run waiting for all humans to be ready
    # Pattern - This shows up for most human actions
    # 1) Human queues action and hits submit, which triggers this endpoint
    # 2) Server checks if all humans have queued actions. If not, just broadcast current state (with a "pending" status) and return.
    # 3) If all humans are ready, step the game instance, which runs all queued actions including AIs, and then broadcast the new state.
    step_ran = await maybe_step_and_broadcast(room)

    if not step_ran:
        return {"status": "pending", "timestep": gi.timestep, "is_alive": is_alive}

    # Generate movement observations (X was seen leaving towards Y)
    observations = generate_room_observations(gi, initial_neighbors, old_room) if is_alive else []
    vent_observations = generate_vent_observations(gi.camera_record, initial_neighbors, old_room) if is_alive else []
    vent_observations += generate_kill_observations(gi.camera_record, initial_neighbors) if is_alive else []
    log_human_action(gi, player, "MOVE", {"from": old_room, "to": new_room})
    return {
        "status": "success",
        "current_room": new_room,
        "timestep": gi.timestep,
        "observations": observations,
        "vent_observations": vent_observations,
        "is_alive" : is_alive
    }

# Handles performing a task
@app.post("/api/do-task")
async def do_task(request: Request, x_player_token: str = Header(...))  -> dict:
    room = get_room(x_player_token)
    gi = room.game_instance
    data = await request.json()
    task_name = data.get("task")

    human_agent = get_human_agent(x_player_token)
    player = human_agent.player
    is_alive = getattr(human_agent.player, 'is_alive', True)

    initial_neighbors = get_players_in_room_except_human(gi, player.location, player)
    task_to_complete = next((t for t in player.tasks if t.name == task_name and not t.check_completion() and t.location == player.location), None)

    if not task_to_complete:
        return {"status": "error", "message": "Error completing task", "observations": []}

    task_room = player.location

    human_agent.queued_action = CompleteTask(current_location=player.location, task=task_to_complete)

    step_ran = await maybe_step_and_broadcast(room)

    if not step_ran:
        return {"status": "pending", "timestep": gi.timestep, "is_alive": is_alive}

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
    log_human_action(gi, player, "COMPLETE_TASK", {"task": task_name, "location": task_room, "progress": f"{steps_done}/{max_dur}"})

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
        await room.game_instance.game_step()
        await broadcast_state(room)
        return {
            "status": "error",
            "message": "Ghosts cannot report bodies!",
            "timestep": gi.timestep,
            "is_alive": is_alive
        }

    # Find unreported corpse at this location using body_location
    dead_player = next((p for p in gi.players if not p.is_alive and not getattr(p, 'reported_death', False) and getattr(p, 'body_location', None) == player.location), None)
    dead_name = get_clean_name(dead_player) if dead_player else "Unknown"

    # Tell engine to call meeting
    human_agent.queued_action = CallMeeting(current_location=player.location)

    # Important: Clear any messages from pre-existing meetings
    if hasattr(gi, 'meeting_messages'):
        gi.meeting_messages = []

    queue_null_actions_for_idle_humans(room)  # Don't block on humans who haven't acted
    await step_and_broadcast(room)

    log_human_action(gi, player, "REPORT", {"body": dead_name, "location": player.location})

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

    human_agent.queued_action = CallMeeting(current_location=player.location)

    if hasattr(gi, 'meeting_messages'):
        gi.meeting_messages = []

    queue_null_actions_for_idle_humans(room)  # Don't block on humans who haven't acted
    await step_and_broadcast(room)

    log_human_action(gi, player, "CALL_MEETING", {"location": player.location})

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
        await room.game_instance.game_step()
        await broadcast_state(room)
        return {
            "status": "error",
            "message": "Ghosts cannot kill others!",
            "timestep": gi.timestep,
            "is_alive": is_alive
        }

    # Find target player object by color
    target_player = next((player for player in gi.players if target_color.lower() in player.name.lower()), None)

    if target_player:
        kill_room = human_player.location
        initial_neighbors = get_players_in_room_except_human(gi, kill_room, human_player)
        human_agent.queued_action = Kill(current_location=kill_room, other_player=target_player)

        step_ran = await maybe_step_and_broadcast(room)
        if not step_ran:
            return {"status": "pending", "timestep": gi.timestep, "is_alive": is_alive}

        observations = generate_room_observations(gi, initial_neighbors, kill_room)
        vent_observations = generate_vent_observations(gi.camera_record, initial_neighbors, kill_room)
        vent_observations += generate_kill_observations(gi.camera_record, initial_neighbors)

        log_human_action(gi, human_player, "KILL", {"target": target_color.capitalize(), "location": human_player.location})

        return{
            "status": "success",
            "message": f"You killed {target_color.capitalize()}!",
            "timestep": gi.timestep,
            "is_alive": is_alive,
            "observations": observations,
            "vent_observations": vent_observations,
        }
    return {
        "status": "error",
        "message": "Error: Target not found.",
        "timestep": gi.timestep,
        "is_alive": is_alive
    }

# Endpoint for sending chat messages during meetings
@app.post("/api/speak")
async def human_speak(request: Request, x_player_token: str = Header(...)) -> dict:
    room = get_room(x_player_token)
    if not room or not room.game_instance:
        return {"error": "No active game session"}
    gi = room.game_instance

    data = await request.json()
    chat_msg = data.get("message", "")

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
    # Execute speak
    action = Speak(current_location=player.location)
    action.provide_message(chat_msg) # Attach the message to the action
    human_agent.queued_action = action
    log_human_action(gi, player, "SPEAK", {"message": chat_msg, "phase": str(gi.current_phase)})

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

    async with room.step_lock:
        if room.meeting_running:
            return {"status": "meeting_in_progress"}
        room.meeting_running = True
        asyncio.create_task(run_meeting_step(room))

    return {"status": "success"}

# Nudge is a null action that is handled by models.py that = Speak with msg (...)
# Used by ghosts to pass their discussion turn
@app.post("/api/set-nudge")
async def set_nudge(x_player_token: str = Header(...)) -> dict:
    human_agent = get_human_agent(x_player_token)
    if not human_agent.player.is_alive:
        human_agent.queued_action = "nudge"
    return {"status": "success"}

# Endpoint for submitting votes during meetings.
# Expects target player color or "none" for skip.
@app.post("/api/vote")
async def handle_vote(request: Request, x_player_token: str = Header(...)) -> dict: 
    room = get_room(x_player_token)
    gi = room.game_instance
    data = await request.json()
    target_color = data.get("target")
    human_agent = get_human_agent(x_player_token)
    player = human_agent.player

    target_player = None

    # Vote for target player and execute action
    if getattr(player, 'is_alive', True):
        if target_color != "none":
            target_player = next((p for p in gi.players if target_color.lower() in p.name.lower()), None)

        human_agent.queued_action = Vote(current_location=human_agent.player.location, other_player=target_player)
        log_human_action(gi, player, "VOTE", {"target": target_color})

    # If meeting_phase is already running, the queued_action will be picked up
    # automatically. Calling game_step() here would start a second meeting phase which is bad
    if getattr(gi, 'meeting_in_progress', False):
        return {"status": "success", "new_phase": "meeting"}

    # Return new phase to JS to hide discussion screen UI
    new_phase = str(gi.current_phase).lower()

    return {
        "status": "success",
        "new_phase": new_phase,
        "message": f"Voting complete. Phase is now {new_phase}"
    }

# 
@app.get("/api/vent-options")
async def get_vent_options(x_player_token: str = Header(...)) -> dict:
    human_agent = get_human_agent(x_player_token)

    # Only alive impostors can vent
    is_impostor = "Impostor" in human_agent.player.__class__.__name__
    is_alive = getattr(human_agent.player, 'is_alive', True)

    if not is_impostor or not is_alive:
        return {"can_vent": False, "options": []}

    current_room = human_agent.player.location

    vent_targets = [
        adj for adj, attr in skeld.ship_map[current_room].items() if attr.get("connection_type") == "vent"
    ]

    return{
        "can_vent": len(vent_targets) > 0,
        "options": vent_targets
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

    # Vent
    human_agent.queued_action = Vent(current_location=human_agent.player.location, new_location=target_room)

    step_ran = await maybe_step_and_broadcast(room)

    if not step_ran:
        return {"status": "pending", "timestep": gi.timestep, "is_alive": is_alive}

    observations = generate_room_observations(gi, initial_neighbors, old_room)
    vent_observations = generate_vent_observations(gi.camera_record, initial_neighbors, old_room)
    vent_observations += generate_kill_observations(gi.camera_record, initial_neighbors)
    log_human_action(gi, player, "VENT", {"from": old_room, "to": target_room})

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
    uvicorn.run(app, host="0.0.0.0", port=8000)
