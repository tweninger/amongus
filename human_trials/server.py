# server.py
import os
import random
import string
import asyncio
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
from serverHelpers import *
from dotenv import load_dotenv

# --- SETUP ---
load_dotenv()

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
        self.last_phase = None # Tracks previous phase to detect transitions
        self.meeting_start_step = None # Timestep when current meeting began
        self.discussion_turn_seq = 0 # Increments each time the discussion baton passes to a new human

# All active rooms keyed by 4 letter code
# token_to_room lets any endpoint find its room from just a player token
games: dict[str, GameRoom] = {}
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

app.mount("/static", StaticFiles(directory=static_path), name="static")

# --- Global HELPER ---
# More helpers in serverHelpers.py

# Get GameRoom given session token
def get_room(token: str):
    code = token_to_room.get(token)
    if code:
        return games.get(code)
    return None

# Given a session token, return the player's WebPlayerAgent
def get_human_agent(token: str):
    room = get_room(token)
    if not room or not room.game_instance:
        return None
    players_idx = room.sessions.get(token)
    if players_idx is not None:
        return room.game_instance.agents[players_idx]
    return None

# Take the next agent slot not yet claimed by a human player
def get_next_open_slot(room: GameRoom):
    taken = set(room.sessions.values()) # set of taken human player indices
    for i, agent in enumerate(room.game_instance.agents):
        if i not in taken and not isinstance(agent, WebPlayerAgent):
            return i
    return None

# Broadcast current game state to all connected players in a room
async def broadcast_state(room: GameRoom):
    gi = room.game_instance
    if not gi:
        return
    current_phase = str(gi.current_phase).lower()
    can_vote = current_phase == "meeting" and getattr(gi, 'discussion_rounds_left', 0) <= 0

    # Detect meeting start/end
    if current_phase == "meeting" and room.last_phase != "meeting":
        room.meeting_start_step = gi.timestep
        room.discussion_turn_seq = 0
    elif current_phase != "meeting" and room.last_phase == "meeting":
        room.meeting_start_step = None
    room.last_phase = current_phase

    # Increment turn sequence whenever a human's waiting_for_action flips to True
    if current_phase == "meeting":
        for agent in gi.agents:
            if isinstance(agent, WebPlayerAgent):
                now_waiting = getattr(agent, 'waiting_for_action', False)
                if now_waiting and not agent._prev_waiting:
                    room.discussion_turn_seq += 1
                agent._prev_waiting = now_waiting

    payload = {
        "type": "state_update",
        "players": [format_player_data(agent.player) for agent in gi.agents],
        "timestep": gi.timestep,
        "phase": current_phase,
        "task_progress": gi.task_assignment.check_task_completion(),
        "winner": get_win_message(gi),
        "vote_result": get_latest_vote_result(gi),
        "meeting_messages": parse_meeting_messages(gi, room.meeting_start_step) if current_phase == "meeting" else [],
        "can_vote": can_vote,
        "discussion_turn_seq": room.discussion_turn_seq,
    }

    dead = []
    for token, ws in room.connections.items():
        try:
            idx = room.sessions.get(token)
            # Different for each player
            is_alive = getattr(gi.agents[idx].player, 'is_alive', True) if idx is not None else True

            # Per-player is_my_turn
            agent = gi.agents[idx] if idx is not None else None
            if current_phase == "meeting":
                if can_vote:
                    # Voting: all alive humans can vote at once
                    is_my_turn = is_alive
                else:
                    # Discussion: only the agent whose choose_action() is currently blocking
                    is_my_turn = (agent is not None and
                                  isinstance(agent, WebPlayerAgent) and
                                  getattr(agent, 'waiting_for_action', False))
            else:
                is_my_turn = True  # During task phase all humans can act freely

            await ws.send_json({**payload, "is_alive": is_alive, "is_my_turn": is_my_turn})

    # Fallback for disconnects
        except Exception:
            dead.append(token)
    for t in dead:
        room.connections.pop(t, None)

# Push a lobby event (roster update or game_started) to all waiting players
async def broadcast_lobby(room: GameRoom, event: str = "lobby_update"):
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


# Returns True if every human has a queued action
def all_humans_ready(room: GameRoom):
    gi = room.game_instance
    for idx in room.sessions.values():
        agent = gi.agents[idx]
        if isinstance(agent, WebPlayerAgent) and agent.queued_action is None:
            if getattr(agent.player, 'is_alive', True):
                return False
    return True

# Step only when all alive humans have queued. 
# Else just broadcast the waiting state.
async def maybe_step_and_broadcast(room: GameRoom):
    if not all_humans_ready(room):
        await broadcast_state(room)
        return False
    async with room.step_lock:
        if not all_humans_ready(room): # Re-check after acquiring lock
            await broadcast_state(room)
            return False
        await room.game_instance.game_step()
    await broadcast_state(room)
    return True

# Run the single long-running meeting game_step as a background task.
# Broadcasts state every second so clients see messages in real time.
async def run_meeting_step(room: GameRoom):
    async def broadcast_loop():
        while room.game_instance and str(room.game_instance.current_phase).lower() == "meeting":
            await broadcast_state(room)
            await asyncio.sleep(1.0)

    broadcast_task = asyncio.create_task(broadcast_loop())
    try:
        await room.game_instance.game_step()
    finally:
        broadcast_task.cancel()
    await broadcast_state(room)  # Final broadcast after meeting ends



# --- API ENDPOINTS ---
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(...)):
    room = get_room(token)
    if not room:
        await websocket.close()
        return

    # Validated, accept the connection and save websocket object in dict    
    await websocket.accept()
    room.connections[token] = websocket

    # Send current state immediately on connect so you are immediately up to date
    if room.game_instance:
        await broadcast_state(room)

    # Event loop
    try:
        while True:
            await websocket.receive_text()

    # Handles leavers
    except WebSocketDisconnect:
        room.connections.pop(token, None)


# Index
@app.get("/")
async def serve_game():
    return FileResponse("templates/game.html")

# Receive player color from frontend, initiate global game instance, and return state to session
@app.post("/api/host")
async def host_game(request: Request):
    data = await request.json()

    setup_log_directory()
    selected_config = get_game_config(data.get("size"))
    total_slots = selected_config.get("num_players", 5) # Max num players
    host_token = str(uuid4()) # Generate a random UUID

    # Initialize engine
    gi = AmongUs(
        game_config=selected_config,
        agent_config={
            "Impostor": "LLM",
            "Crewmate": "LLM",
            "IMPOSTOR_LLM_CHOICES": ["google/gemini-2.0-flash-001"],
            "CREWMATE_LLM_CHOICES": ["google/gemini-2.0-flash-001"],
        }
    )

    gi.initialize_game()

    # DEBUG
    # --- INITIAL ASSIGNMENT PRINT ---
    print("\n=== INITIAL TASK ROSTER ===")
    for p in gi.players:
        p_color = p.name.split()[-1]
        task_list = [t.name for t in p.tasks]
        print(f"{p_color.upper()}: {task_list}")
    print("===========================\n")

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

    room = GameRoom(
        size_config=selected_config,
        total_slots=total_slots,
        host_token=host_token,
        host_color=host_color,
    )
    room.game_instance = gi
    room.sessions[host_token] = 0
    games[code] = room # Stores the entire game state under the 4-letter code
    token_to_room[host_token] = code # Maps hosts ID to that room code

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
async def join_game(request: Request):
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
async def list_lobbies():
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
async def start_game(x_player_token: str = Header(...)):
    room = get_room(x_player_token)
    if not room or not room.game_instance:
        return {"status": "error", "message": "Room not found"}
    if x_player_token != room.host_token:
        return {"status": "error", "message": "Only the host can start the game"}
 
    # Start the game by setting phase to active
    room.status = "active"
    room.game_instance.game_phase = "active"
    room.game_instance.activity_log.append("Host started the game.")

    # Tell all connected clients to transition to the game screen
    await broadcast_lobby(room, event="game_started")

    return {"status": "success", "phase": room.game_instance.game_phase}

# Get high level game data
@app.get("/api/game-state")
async def get_game_state(x_player_token: str = Header(None)):
    room = get_room(x_player_token) if x_player_token else None
    # If no game, send null stats
    if not room or not room.game_instance:
        return {
            "phase": "lobby",
            "timestep": 0,
            "winner": None,
            "task_progress": 0
        }
    gi = room.game_instance
    task_progress = gi.task_assignment.check_task_completion() # is a decimal

    return {
        "phase": str(gi.current_phase).lower(),
        "timestep": gi.timestep,
        "winner": get_win_message(gi),
        "task_progress": task_progress
    }


# Retrieves current game state and meeting context for the human player
# Helps in determining phase transitions, turn availability, and discussion history
@app.get("/api/meeting-context")
async def get_meeting_context(x_player_token: str = Header(...)):
    room = get_room(x_player_token)
    if not room or not room.game_instance:
        return {"phase": "lobby"}
    gi = room.game_instance

    try:
        agent = get_human_agent(x_player_token)

        current_phase = str(getattr(gi, 'current_phase', 'active')).lower()

        # Is it time for the human to vote?
        can_vote = (current_phase == "meeting" and getattr(gi, 'discussion_rounds_left', 0) <= 0)

        # Get meeting msgs for front end
        meeting_messages = parse_meeting_messages(gi) if current_phase == "meeting" else []

        # Turn management
        is_alive = getattr(agent.player, 'is_alive', True)

        # Are we in a meeting and its our turn according to game_instance backend?
        is_my_turn = (current_phase == "meeting" and getattr(gi, 'is_human_turn', False))
        return {
            "status": "online",
            "phase": current_phase,
            "timestep": gi.timestep,
            "is_alive": is_alive,
            "is_my_turn": is_my_turn,
            "can_vote": can_vote,
            "meeting_messages": meeting_messages,
            "winner": get_win_message(gi),
            "vote_result": get_latest_vote_result(gi),
        }

    except Exception as e:
        return {"phase": "error", "details": str(e)}

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

    # Tasks left to do
    personal_tasks = [
        {
            "name": task.name,
            "max_duration": task.max_duration,
            "steps_done": task.max_duration - task.duration,
        }
        for task in all_incomplete
    ]

    # Map each task name to the locations where it can be completed
    task_locations = get_task_location_map([t["name"] for t in personal_tasks])

    # Everyone in the same room except the human player themselves
    others_in_room = [
        format_player_data(a.player)
        for a in gi.agents
        if a.player.location == current_room and a != agent
    ]

    return {
        "current_room": current_room,
        "phase": str(gi.current_phase),
        "adjacent": skeld.get_adjacent_rooms(current_room),
        "tasks_in_room": room_data.get(current_room, {}).get("tasks", []),
        "personal_tasks": personal_tasks,
        "task_locations": task_locations,
        "timestep": gi.timestep,
        "players_in_room": others_in_room,
        "is_alive": getattr(player, 'is_alive', True)
    }

# Handles moving, trigers AI turns, and generates movement observations
@app.post("/api/move")
async def move_player(request: Request, x_player_token: str = Header(...)):
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
    step_ran = await maybe_step_and_broadcast(room)

    if not step_ran:
        return {"status": "pending", "timestep": gi.timestep, "is_alive": is_alive}

    if not is_alive:
        player.location = new_room
        await broadcast_state(room)

    # Generate movement observations (X was seen leaving towards Y)
    observations = generate_room_observations(gi, initial_neighbors, old_room) if is_alive else []
    vent_observations = generate_vent_observations(gi.camera_record, initial_neighbors, old_room) if is_alive else []
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
async def do_task(request: Request, x_player_token: str = Header(...)):
    room = get_room(x_player_token)
    gi = room.game_instance
    data = await request.json()
    task_name = data.get("task")

    human_agent = get_human_agent(x_player_token)
    player = human_agent.player
    is_alive = getattr(human_agent.player, 'is_alive', True)

    initial_neighbors = get_players_in_room_except_human(gi, player.location, player)
    task_to_complete = next((t for t in player.tasks if t.name == task_name and not t.check_completion()), None)

    if not task_to_complete:
        return {"status": "error", "message": "Task not found or completed", "observations": []}

    task_room = player.location

    human_agent.queued_action = CompleteTask(current_location=player.location, task=task_to_complete)


    step_ran = await maybe_step_and_broadcast(room)

    if not step_ran:
        return {"status": "pending", "timestep": gi.timestep, "is_alive": is_alive}

    if not is_alive:
        task_to_complete.do_task()
        await broadcast_state(room)

    # Build progress message
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
async def report_body(request: Request, x_player_token: str = Header(...)):
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

    # Check who is dead in the room
    players_here = gi.map.get_players_in_room(player.location, include_new_deaths=True)
    dead_name = get_fresh_corpse_name(players_here)

    # Tell engine to call meeting
    human_agent.queued_action = CallMeeting(current_location=player.location)

    if hasattr(gi, 'meeting_messages'):
        # Clear msgs from previous meetings
        gi.meeting_messages = []

    # Step the engine, moving everyone to cafeteria
    await step_and_broadcast(room)

    # Initiate the meeting
    await step_and_broadcast(room)

    log_human_action(gi, player, "REPORT", {"body": dead_name, "location": player.location})

    return {
        "status": "success",
        "message": f"🚨 {human_agent.player.name.split(':')[-1].strip().capitalize()} reported {dead_name}'s body!",
        "timestep": gi.timestep,
        "phase": gi.current_phase,
        "is_alive": is_alive
    }

@app.post("/api/kill")
async def kill_player(request: Request, x_player_token: str = Header(...)):
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
    target_player = next((player for player in gi.players if player.name.split()[-1].lower() == target_color.lower()), None)

    if target_player:
        kill_room = human_player.location
        initial_neighbors = get_players_in_room_except_human(gi, kill_room, human_player)
        human_agent.queued_action = Kill(current_location=human_player.location, other_player=target_player)

        step_ran = await maybe_step_and_broadcast(room)
        if not step_ran:
            return {"status": "pending", "timestep": gi.timestep, "is_alive": is_alive}

        observations = generate_room_observations(gi, initial_neighbors, kill_room)
        vent_observations = generate_vent_observations(gi.camera_record, initial_neighbors, kill_room)

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

@app.post("/api/speak")
async def human_speak(request: Request, x_player_token: str = Header(...)):
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
    action.provide_message(chat_msg)
    human_agent.queued_action = action
    log_human_action(gi, player, "SPEAK", {"message": chat_msg, "phase": str(gi.current_phase)})

    return {
        "status": "success",
        "timestep": gi.timestep,
        "is_alive": True
    }

@app.post("/api/next-step")
async def next_step(x_player_token: str = Header(...)):
    room = get_room(x_player_token)
    if not room or not room.game_instance:
        return {"error": "No game"}
    gi = room.game_instance

    current_phase = str(gi.current_phase).lower()
    if current_phase != "meeting":
        return {"status": "not_meeting"}

    if getattr(gi, 'meeting_in_progress', False):
        return {"status": "meeting_in_progress"}

    async with room.step_lock:
        if getattr(gi, 'meeting_in_progress', False):
            return {"status": "meeting_in_progress"}
        asyncio.create_task(run_meeting_step(room))

    return {"status": "success"}

# Nudge is a null action that is handled by models.py that = Speak with msg (...)
# Used by ghosts to pass their discussion turn
@app.post("/api/set-nudge")
async def set_nudge(x_player_token: str = Header(...)):
    human_agent = get_human_agent(x_player_token)
    if not human_agent.player.is_alive:
        human_agent.queued_action = "nudge"
    return {"status": "success"}

@app.post("/api/vote")
async def handle_vote(request: Request, x_player_token: str = Header(...)):
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

    print(f"DEBUG: Human voting for {target_player.name if target_player else 'none (skip)'}")

    # Return new phase to JS to hide discussion screen UI
    new_phase = str(gi.current_phase).lower()
    print(f"DEBUG: Meeting ended. New Phase: {new_phase}")

    return {
        "status": "success",
        "new_phase": new_phase,
        "message": f"Voting complete. Phase is now {new_phase}"
    }

@app.get("/api/vent-options")
async def get_vent_options(x_player_token: str = Header(...)):
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
