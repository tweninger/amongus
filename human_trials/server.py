# server.py
import os
import uvicorn
from fastapi import FastAPI, Request
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

# Initiatialize default game state
game_instance = None

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
# Return human agent as the 0th agent (always index 0)
def get_human_agent():
    if not game_instance or not game_instance.agents:
        return None
    return game_instance.agents[0]

# --- API ENDPOINTS ---

# Index
@app.get("/")
async def serve_game():
    return FileResponse("templates/game.html")

# Receive player color from frontend, initiate global game instance, and return state to session
@app.post("/api/join")
async def join_game(request: Request):
    global game_instance
    data = await request.json()

    setup_log_directory()
    selected_config = get_game_config(data.get("size"))

    # Initialize engine
    game_instance = AmongUs(
        game_config=selected_config,
        agent_config={
            "Impostor": "LLM", 
            "Crewmate": "LLM",
            "IMPOSTOR_LLM_CHOICES": ["google/gemini-2.0-flash-001"], 
            "CREWMATE_LLM_CHOICES": ["google/gemini-2.0-flash-001"],
        }
    )

    game_instance.initialize_game()

    # DEBUG
    # --- INITIAL ASSIGNMENT PRINT ---
    print("\n=== INITIAL TASK ROSTER ===")
    for p in game_instance.players:
        p_color = p.name.split()[-1]
        task_list = [t.name for t in p.tasks]
        print(f"{p_color.upper()}: {task_list}")
    print("===========================\n")

    # Convert Agent 0 to the human and retrieve attributes
    game_instance.agents[0] = WebPlayerAgent(game_instance.players[0])
    human_agent = game_instance.agents[0]
    human_color = human_agent.player.name.split()[-1].lower()
    human_agent.player.name = human_color.capitalize()
    human_role = human_agent.player.__class__.__name__

    # Prepare Staging
    game_instance.game_phase = "staging"
    roster = get_roster(game_instance.agents)

    return {
        "role": human_role,
        "color": human_color,
        "current_room": human_agent.player.location,
        "timestep": game_instance.timestep,
        "roster": roster
    }

# Send response to start game
@app.post("/api/ready")
async def start_game_loop():
    global game_instance
    if not game_instance:
        return {"event": "Game not initialized"} 
    game_instance.game_phase = "active"
    game_instance.activity_log.append("All players are ready. Starting game.")

    return {"status": "success", "phase": game_instance.game_phase}

# Get high level game data
@app.get("/api/game-state")
async def get_game_state():
    # If no game, send null stats
    if game_instance is None:
        return {
            "phase": "lobby",
            "timestep": 0,
            "winner": None,
            "task_progress": 0
        }

    task_progress = game_instance.task_assignment.check_task_completion() # is a decimal

    return {
        "phase": str(game_instance.current_phase).lower(),
        "timestep": game_instance.timestep,
        "winner": get_win_message(game_instance),
        "task_progress": task_progress
    }


# Retrieves current game state and meeting context for the human player
# Helps in determining phase transitions, turn availability, and discussion history
@app.get("/api/meeting-context")
async def get_meeting_context():
    global game_instance
    if not game_instance:
        return {"phase": "lobby"}

    try:
        agent = get_human_agent()

        current_phase = str(getattr(game_instance, 'current_phase', 'active')).lower()

        # Is it time for the human to vote?
        can_vote = (current_phase == "meeting" and getattr(game_instance, 'discussion_rounds_left', 0) <= 0)

        # Get meeting msgs for front end
        meeting_messages = parse_meeting_messages(game_instance) if current_phase == "meeting" else []

        # Turn management
        is_alive = getattr(agent.player, 'is_alive', True)

        # Are we in a meeting and its our turn according to game_instance backend?
        is_my_turn = (current_phase == "meeting" and getattr(game_instance, 'is_human_turn', False))
        return {
            "status": "online",
            "phase": current_phase,
            "timestep": game_instance.timestep,
            "is_alive": is_alive,
            "is_my_turn": is_my_turn,
            "can_vote": can_vote,
            "meeting_messages": meeting_messages,
            "winner": get_win_message(game_instance),
            "vote_result": get_latest_vote_result(game_instance),
        }

    except Exception as e:
        return {"phase": "error", "details": str(e)}

# Iterates through all agents and returning list of various stats for frontend UI rendering
@app.get("/api/player-states")
async def get_map_state():
    global game_instance
    if not game_instance:
        return {"error": "Game not initialized"}
    
    return {
        # name, color, location, is_alive, reported_death, identity
        "players": [format_player_data(agent.player) for agent in game_instance.agents]
    }

# Returns everything the frontend needs to render the human player's current room view
# Location, phase, adjacent rooms, available tasks, and other players present in current room
@app.get("/api/room-context")
async def get_room_context():
    if not game_instance:
        return {"error": "Game not initialized"}

    agent = get_human_agent()
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
        for a in game_instance.agents
        if a.player.location == current_room and a != agent
    ]

    return {
        "current_room": current_room,
        "phase": str(game_instance.current_phase),
        "adjacent": skeld.get_adjacent_rooms(current_room),
        "tasks": room_data.get(current_room, {}).get("tasks", []),
        "personal_tasks": personal_tasks,
        "task_locations": task_locations,
        "timestep": game_instance.timestep,
        "players_in_room": others_in_room,
        "is_alive": getattr(player, 'is_alive', True)
    }

# Handles moving, trigers AI turns, and generates movement observations
@app.post("/api/move")
async def move_player(request: Request):
    global game_instance
    data = await request.json()
    new_room = data.get("destination")

    human_agent = get_human_agent()
    player = human_agent.player
    is_alive = getattr(player, 'is_alive', True)

    initial_neighbors = get_players_in_room_except_human(game_instance, player.location, player)
    old_room = player.location

    # Human executes movement
    human_agent.queued_action = MoveTo(current_location=old_room, new_location=new_room)

    # Await AI agent run
    await game_instance.game_step()

    # Spectator / Ghost Mode: Need to manually override location
    if not is_alive:
        player.location = new_room
        # Need to log manually since skipped by the engine
        game_instance.activity_log.append({
            "timestep": game_instance.timestep,
            "phase": game_instance.current_phase,
            "action": f"GHOST_MOVE: {player.name} moved to {new_room}",
            "player": player
        })
    # Generate movement observations (X was seen leaving towards Y)
    observations = generate_room_observations(game_instance, initial_neighbors, old_room)
    vent_observations = generate_vent_observations(game_instance.camera_record, initial_neighbors, old_room)
    log_human_action(game_instance, player, "MOVE", {"from": old_room, "to": player.location})
    return {
        "status": "success",
        "current_room": player.location,
        "timestep": game_instance.timestep,
        "observations": observations,
        "vent_observations": vent_observations,
        "is_alive" : is_alive
    }

# Handles performing a task
@app.post("/api/do-task")
async def do_task(request: Request):
    global game_instance
    data = await request.json()
    task_name = data.get("task")

    human_agent = get_human_agent()
    player = human_agent.player
    is_alive = getattr(human_agent.player, 'is_alive', True)

    initial_neighbors = get_players_in_room_except_human(game_instance, player.location, player)
    task_to_complete = next((t for t in player.tasks if t.name == task_name and not t.check_completion()), None)

    if not task_to_complete:
        return {"status": "error", "message": "Task not found or completed", "observations": []}
    
    task_room = player.location
    human_agent.queued_action = CompleteTask(current_location=player.location, task=task_to_complete)
    await game_instance.game_step()

    if not is_alive:
        # Ghost logic
        task_to_complete.do_task()
        game_instance.activity_log.append({
            "timestep": game_instance.timestep,
            "phase": game_instance.current_phase,
            "action": f"GHOST_TASK: {player.name} completed {task_name}",
            "player": player
        })
        await game_instance.game_step()

    # Build progress message
    steps_done = task_to_complete.max_duration - task_to_complete.duration
    max_dur = task_to_complete.max_duration
    if task_to_complete.check_completion():
        msg = f"You completed {task_name}!"
        if max_dur > 1:
            msg = f"You completed {task_name}! ({max_dur}/{max_dur})"
    else:
        msg = f"Working on {task_name}... ({steps_done}/{max_dur})"

    # Generate movement observations (X was seen leaving towards Y)
    observations = generate_room_observations(game_instance, initial_neighbors, player.location)
    vent_observations = generate_vent_observations(game_instance.camera_record, initial_neighbors, task_room)
    log_human_action(game_instance, player, "COMPLETE_TASK", {"task": task_name, "location": task_room, "progress": f"{steps_done}/{max_dur}"})

    return {
        "status": "success",
        "message": msg,
        "timestep": game_instance.timestep,
        "observations": observations,
        "vent_observations": vent_observations,
        "is_alive": is_alive
    }

# Endpoint for reporting dead body
@app.post("/api/report")
async def report_body(request: Request):
    global game_instance
    if not game_instance:
        return {"error": "Game not initialized"}
    
    human_agent = get_human_agent()
    player = human_agent.player
    is_alive = getattr(player, 'is_alive', True)

    # Guard for ghosts
    if not is_alive:
        await game_instance.game_step()
        return {
            "status": "error", 
            "message": "Ghosts cannot report bodies!",
            "timestep": game_instance.timestep,
            "is_alive": is_alive
        }

    # Check who is dead in the room
    players_here = game_instance.map.get_players_in_room(player.location, include_new_deaths=True)
    dead_name = get_fresh_corpse_name(players_here)

    # Tell engine to call meeting
    human_agent.queued_action = CallMeeting(current_location=player.location)

    if hasattr(game_instance, 'meeting_messages'):
        # Clear msgs from previous meetings
        game_instance.meeting_messages = []

    # Step the engine, moving everyone to cafeteria
    await game_instance.game_step()

    # Initiate the meeting
    await game_instance.game_step()

    log_human_action(game_instance, player, "REPORT", {"body": dead_name, "location": player.location})

    return {
        "status": "success",
        "message": f"🚨 {human_agent.player.name.split(':')[-1].strip().capitalize()} reported {dead_name}'s body!",
        "timestep": game_instance.timestep,
        "phase": game_instance.current_phase,
        "is_alive": is_alive
    }

@app.post("/api/kill")
async def kill_player(request: Request):
    global game_instance
    data = await request.json()
    target_color = data.get("target")

    human_agent = get_human_agent()
    if not human_agent:
        return {"status": "error", "message": "No human agent found"}
    human_player = human_agent.player
    is_alive = getattr(human_player, 'is_alive', True)

    # Guard for Ghosts
    if not is_alive:
        await game_instance.game_step()
        return {
            "status": "error",
            "message": "Ghosts cannot kill others!",
            "timestep": game_instance.timestep,
            "is_alive": is_alive
        }

    # Find target player object by color
    target_player = next(
        (p for p in game_instance.players if p.name.split()[-1].lower() == target_color.lower()),
        None
    )

    if target_player:
        kill_room = human_player.location
        initial_neighbors = get_players_in_room_except_human(game_instance, kill_room, human_player)
        human_agent.queued_action = Kill(current_location=human_player.location, other_player=target_player)
        await game_instance.game_step()

        observations = generate_room_observations(game_instance, initial_neighbors, kill_room)
        vent_observations = generate_vent_observations(game_instance.camera_record, initial_neighbors, kill_room)

        log_human_action(game_instance, human_player, "KILL", {"target": target_color.capitalize(), "location": human_player.location})
        return{
            "status": "success",
            "message": f"You killed {target_color.capitalize()}!",
            "timestep": game_instance.timestep,
            "is_alive": is_alive,
            "observations": observations,
            "vent_observations": vent_observations,
        }
    return {
        "status": "error", 
        "message": "Error: Target not found.",
        "timestep": game_instance.timestep,
        "is_alive": is_alive
    }

@app.post("/api/speak")
async def human_speak(request: Request):
    global game_instance
    if not game_instance:
        return {"error": "No active game session"}

    data = await request.json()
    chat_msg = data.get("message", "")

    human_agent = get_human_agent()
    player = human_agent.player
    is_alive = getattr(player, 'is_alive', True)

    # Guard for Ghosts
    if not is_alive:
        return {
            "status": "error", 
            "message": "Ghosts can't talk!",
            "timestep": game_instance.timestep,
            "is_alive": is_alive
        }
    # Execute speak
    action = Speak(current_location=player.location)
    action.provide_message(chat_msg)
    human_agent.queued_action = action
    log_human_action(game_instance, player, "SPEAK", {"message": chat_msg, "phase": str(game_instance.current_phase)})

    return {
        "status": "success",
        "timestep": game_instance.timestep,
        "is_alive": True
    }

# Steps forward one, primarily used during meetings
@app.post("/api/next-step")
async def next_step():
    global game_instance
    if not game_instance:
        return {"error": "No game"}

    if game_instance.is_human_turn:
        # If meeting_phase is already running, queued_action will be picked up
        # automatically, starting a second concurrent meeting_phase breaks things.
        if getattr(game_instance, 'meeting_in_progress', False):
            return {"status": "meeting_in_progress"}
        await game_instance.game_step()
        return {"status": "success"}

    return {"status": "error", "reason": "Not your Turn!"}

# Nudge is a null action that is handled by models.py that = Speak with msg (...)
# Used by ghosts to pass their discussion turn
@app.post("/api/set-nudge")
async def set_nudge():
    human_agent = get_human_agent()
    if not human_agent.player.is_alive:
        human_agent.queued_action = "nudge"
    return {"status": "success"}

@app.post("/api/vote")
async def handle_vote(request: Request):
    global game_instance
    data = await request.json()
    target_color = data.get("target")
    human_agent = get_human_agent()
    player = human_agent.player

    target_player = None
    if getattr(player, 'is_alive', True):
        if target_color != "none":
            target_player = next((p for p in game_instance.players if target_color.lower() in p.name.lower()), None)

        human_agent.queued_action = Vote(current_location=human_agent.player.location, other_player=target_player)
        log_human_action(game_instance, player, "VOTE", {"target": target_color})

    # If meeting_phase is already running, the queued_action will be picked up
    # automatically. Calling game_step() here would start a second meeting phase which is bad
    if getattr(game_instance, 'meeting_in_progress', False):
        return {"status": "success", "new_phase": "meeting"}

    print(f"DEBUG: Human voting for {target_player.name}")
    # Return new phase to JS to hide discussion screen UI
    new_phase = str(game_instance.current_phase).lower()
    print(f"DEBUG: Meeting ended. New Phase: {new_phase}")

    return {
        "status": "success",
        "new_phase": new_phase,
        "message": f"Voting complete. Phase is now {new_phase}"
    }

@app.get("/api/vent-options")
async def get_vent_options():
    global game_instance
    human_agent = get_human_agent()

    # Only alive impostors can vent
    is_impostor = "Impostor" in human_agent.player.__class__.__name__
    is_alive = getattr(human_agent, 'is_alive', True)

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
async def perform_vent(request: Request):
    global game_instance
    data = await request.json()
    target_room = data.get("destination")

    human_agent = get_human_agent()
    player = human_agent.player
    is_alive = getattr(player, 'is_alive', True)

    # Capture stats before venting for observations
    initial_neighbors = get_players_in_room_except_human(game_instance, player.location, player)
    old_room = player.location

    # Ghost Guard
    if not is_alive:
        await game_instance.game_step()
        return {
            "status": "error",
            "message": "Ghosts cannot vent!",
            "timestep": game_instance.timestep,
            "is_alive": False
        }

    # Vent
    human_agent.queued_action = Vent(current_location=human_agent.player.location, new_location=target_room)

    await game_instance.game_step()

    observations = generate_room_observations(game_instance, initial_neighbors, old_room)
    vent_observations = generate_vent_observations(game_instance.camera_record, initial_neighbors, old_room)
    log_human_action(game_instance, player, "VENT", {"from": old_room, "to": target_room})

    return {
        "status": "success",
        "current_room": target_room,
        "timestep": game_instance.timestep,
        "message": f"You vented to {target_room.replace('_', ' ').capitalize()}.",
        "is_alive": is_alive,
        "observations": observations,
        "vent_observations": vent_observations,
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)