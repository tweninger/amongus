# server.py
import os
import sys
import uvicorn
import networkx as nx
import asyncio
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

current_dir = os.path.dirname(os.path.abspath(__file__))
research_path = os.path.abspath(os.path.join(current_dir, "..", "among-agents"))

if research_path not in sys.path:
    sys.path.append(research_path)

from amongagents.envs.game import AmongUs
from amongagents.envs.configs.map_config import room_data, connections, vent_connections
from amongagents.envs.configs.game_config import FIVE_MEMBER_GAME, SEVEN_MEMBER_GAME
from amongagents.envs.action import CompleteTask, MoveTo, CallMeeting, Kill
from dotenv import load_dotenv

load_dotenv()

# Construct the map of Skeld for play
class Map:
    def __init__(self):
        self.ship_map = nx.Graph()
        
        for room_name, details in room_data.items():
            self.ship_map.add_node(room_name, **details)

        for room1, room2 in connections:
            self.ship_map.add_edge(room1, room2, connection_type="corridor")

        for room1, room2 in vent_connections:
            self.ship_map.add_edge(room1, room2, connection_type="vent")

    # Given room, get connected rooms by corridor
    def get_adjacent_rooms(self, room_name):
        if room_name not in self.ship_map:
            return []
        return [
            adj for adj, attr in self.ship_map[room_name].items()
            # Can be accessed by all
            if attr["connection_type"] == "corridor"
        ]
skeld = Map()

class WebPlayerAgent:
    def __init__(self, player):
        self.player = player
        self.model = "homosapiens/web"
        self.queued_action = None

    async def choose_action(self, timestep):
        # Give queued action to engine
        action = self.queued_action
        self.queued_action = None
        return action

    def choose_observation_location(self, map):
        return self.player.location

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
# /static -> static_path folder
app.mount("/static", StaticFiles(directory=static_path), name="static")

# Init default game state 
game_instance = None

# Index
@app.get("/")
async def serve_game():
    return FileResponse("templates/game.html")

# Receive player name from frontend, initiate global game instance, and return state to session
@app.post("/api/join")
async def join_game(request: Request):
    global game_instance
    data = await request.json()
    game_size = data.get("size", "FIVE_MEMBER_GAME")

    config_map = {
        "FIVE_MEMBER_GAME": FIVE_MEMBER_GAME,
        "SEVEN_MEMBER_GAME": SEVEN_MEMBER_GAME
    }

    selected_config = config_map.get(game_size, FIVE_MEMBER_GAME)

    # Correct path setup
    log_dir = os.path.join(os.getcwd(), "logs")
    os.makedirs(log_dir, exist_ok=True)
    os.environ["EXPERIMENT_PATH"] = log_dir

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
    # --- INITIAL ASSIGNMENT PRINT ---
    print("\n=== INITIAL TASK ROSTER ===")
    for p in game_instance.players:
        p_color = p.name.split()[-1]
        task_list = [t.name for t in p.tasks]
        print(f"{p_color.upper()}: {task_list}")
    print("===========================\n")

    # Convert Agent 0 to the human
    game_instance.agents[0] = WebPlayerAgent(game_instance.players[0])
    human_agent = game_instance.agents[0]
    human_color = human_agent.player.name.split()[-1].lower()

    # Update the player object's name
    human_agent.player.name = human_color.capitalize()
    human_role = human_agent.player.__class__.__name__

    # Build roster for staging phase checklist
    roster = []
    for i, agent in enumerate(game_instance.agents):
        agent_color = agent.player.name.split()[-1].lower()
        agent_name = agent_color.capitalize()

        roster.append({
            "id": i,
            "name": agent_name,
            "color": agent_color,
            "is_human": i == 0
        })

    game_instance.game_phase = "staging"

    return {
        "role": human_role,
        "color": human_color,
        "current_room": human_agent.player.location,
        "timestep": game_instance.timestep,
        "roster": roster
    }

@app.post("/api/ready")
async def start_game_loop():
    global game_instance
    if not game_instance:
        return {"event": "Game not initialized"} 
    game_instance.game_phase = "active"
    game_instance.activity_log.append("All players are ready. Starting game.")

    return {"status": "success", "phase": game_instance.game_phase}


@app.get("/api/status")
async def get_status():
    global game_instance
    if not game_instance:
        return {"status": "Waiting", "event": "No game", "timestep": 0}

    try:
        if game_instance.activity_log:
            last_log = str(game_instance.activity_log[-1]) 
        else:
            last_log = "Turn complete"

        return {
            "status": game_instance.game_phase,
            "event": last_log,
            "timestep": game_instance.timestep
        }
    except Exception as e:
        print(f"STATUS ERROR: {e}")
        return {"status": "Error", "event": str(e)}


@app.get("/api/map-state")
async def get_map_state():
    global game_instance
    if not game_instance:
        return {"error": "Game not initialized"}

    player_locations = []

    # Get human player if exists
    all_players = []
    if hasattr(game_instance, 'human_player'):
        all_players.append(game_instance.human_player)

    # Add AI players
    for agent in game_instance.agents:
        all_players.append(agent.player)

    # Build locations list
    for player in all_players:
        color = player.name.split()[-1].lower() 
        
        player_locations.append({
            "name": color.capitalize(),
            "color": color,
            "location": player.location
        })

    return {"players": player_locations}

# Get current room, connected rooms, current tasks available, and players sharing your room (+ DOA status)
@app.get("/api/room-context")
async def get_room_context():
    global game_instance
    if not game_instance:
        return {"error": "Game not initialized"}
 
    human_player = game_instance.agents[0].player
    current_room = human_player.location

    # Get human's assigned tasks from the engine
    personal_tasks = []
    for task in human_player.tasks:
        if not task.check_completion(): # Only send incomplete tasks to UI
            personal_tasks.append(task.name)

    # Map your personal tasks to locations
    task_locations = {}
    for task in personal_tasks:
        found_rooms = []
        for room_name, details in room_data.items():
            if task in details.get("tasks", []):
                found_rooms.append(room_name)
 
        if found_rooms:
            task_locations[task] = " or ".join(found_rooms)
        else:
            task_locations[task] = "Unknown"

    # Get possible moves from the map logic
    possible_moves = skeld.get_adjacent_rooms(current_room)

    # Get tasks for this room
    current_tasks = room_data.get(current_room, {}).get("tasks", [])

    players_in_room = []

    for i, agent in enumerate(game_instance.agents):
        # skip yourself (agent 0)
        if i == 0:
            continue

        if agent.player.location == current_room:

            # Check engine's built-in status flags
            is_alive = getattr(agent.player, 'is_alive', True)
            reported_death = getattr(agent.player, 'reported_death', False)
            color = agent.player.name.split()[-1].lower()

            # Check if the agent is alive or dead
            players_in_room.append({
                "name": color.capitalize(),
                "color": color,
                "is_alive": is_alive,
                "reported_death": getattr(agent.player, 'reported_death', False)
            })

    return {
        "current_room": current_room,
        "phase": game_instance.current_phase,
        "adjacent": possible_moves,
        "tasks": current_tasks,
        "personal_tasks": personal_tasks,
        "task_locations": task_locations,
        "timestep": game_instance.timestep,
        "players_in_room": players_in_room
    }

# Handles moving, trigers AI turns, and generates movement observations
@app.post("/api/move")
async def move_player(request: Request):
    global game_instance
    data = await request.json()
    new_room = data.get("destination")

    human_player = game_instance.agents[0]
    current_room = human_player.player.location

    players_here = [player for player in game_instance.map.get_players_in_room(current_room) if player != human_player.player]

    # Human executes movement
    action = MoveTo(current_location=current_room, new_location=new_room)
    human_player.queued_action = action

    # Await AI agents run
    await game_instance.game_step()

    # Generate movement observations (X was seen leaving towards Y)
    observations = []
    for player in players_here:
        if player.location != current_room:
            observation_msg = f"Observation: {player.name.split()[-1].capitalize()} was seen leaving towards {player.location}."
            observations.append(observation_msg)
            game_instance.activity_log.append(f"Step {game_instance.timestep}: {observation_msg}")

    return {
        "status": "success",
        "current_room": new_room,
        "timestep": game_instance.timestep,
        "observations": observations
    }

# Handles performing a task
@app.post("/api/do-task")
async def do_task(request: Request):
    global game_instance
    data = await request.json()
    task_name = data.get("task")

    human_player = game_instance.agents[0]
    current_room = human_player.player.location

    players_here = [player for player in game_instance.map.get_players_in_room(current_room) if player != human_player.player]
    task_to_complete = None
    for task in human_player.player.tasks:
        if task.name == task_name and not task.check_completion():
            task_to_complete = task
            break
    if task_to_complete:
        action = CompleteTask(current_location=current_room, task=task_to_complete)
        human_player.queued_action = action

    action_msg = f"{human_player.player.name} completed {task_name}"

    # Await AI agents run
    await game_instance.game_step()

    # Generate movement observations (X was seen leaving towards Y)
    observations = []
    for player in players_here:
        if player.location != current_room:
            observation_msg = f"Observation: {player.name.split()[-1].capitalize()} was seen leaving towards {player.location}."
            observations.append(observation_msg)
            game_instance.activity_log.append(f"Step {game_instance.timestep}: {observation_msg}")

    return {
        "status": "success",
        "message": action_msg,
        "timestep": game_instance.timestep,
        "observations": observations
    }

@app.post("/api/report")
async def report_body(request: Request):
    global game_instance
    if not game_instance:
        return {"error": "Game not initialized"}

    human_agent = game_instance.agents[0]
    current_room = human_agent.player.location

    # Check who is dead in the room
    dead_name = "Unknown"
    players_here = game_instance.map.get_players_in_room(current_room, include_new_deaths=True)
    for player in players_here:
        if not player.is_alive and not player.reported_death:
            dead_name = player.name.split(":")[0]
            break
    action = CallMeeting(current_location = current_room)
    human_agent.queued_action = action

    # Step the engine, moving everyone to cafeteria and changing phases
    asyncio.create_task(game_instance.game_step())

    return {
        "status": "success",
        "message": f"🚨 {human_agent.player.name.split(':')[0]} reported {dead_name}'s body!",
        "timestep": game_instance.timestep,
        "phase": game_instance.current_phase
    }

@app.post("/api/kill")
async def kill_player(request: Request):
    global game_instance
    data = await request.json()

    # Returns victim color
    target_color = data.get("target")

    human_agent = game_instance.agents[0]
    current_room = human_agent.player.location

    target_player = None
    # Find target player object by color
    for player in game_instance.players:
        if player.name.split()[-1].lower() == target_color.lower():
            target_player = player
            break

    if target_player:
        action = Kill(current_location=current_room, other_player=target_player)
        human_agent.queued_action = action

        # Step the engine
        await game_instance.game_step()

        return{
            "status": "success",
            "message": f"You killed {target_color.capitalize()}!",
            "timestep": game_instance.timestep
        }

    return {"status": "error", "message": "Error: Target not found."}
# Debugging
@app.get("/api/cheat-kill")
async def cheat_kill():
    # Instantly kill Player 2 (or anyone else) to test the report button
    if len(game_instance.players) > 1:
        target = game_instance.players[1]
        target.is_alive = False
        return {"status": f"Killed {target.name}"}
    return {"error": "Not enough players"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)