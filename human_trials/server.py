# server.py
import os
import sys
import uvicorn
import networkx as nx
import random
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
from amongagents.envs.configs.game_config import THREE_MEMBER_GAME, FIVE_MEMBER_GAME, SEVEN_MEMBER_GAME
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

    # Task Generation for Everyone
    task_pools = {
        "common": ["Fix Wiring", "Swipe Card"],
        "long": ["Empty Garbage", "Clear Asteroids", "Empty Chute", "Align Engine Output", "Fuel Engines", "Start Reactor", "Inspect Sample"],
        "short": ["Download Data", "Accept Diverted Power", "Chart Course", "Stabilize Steering", "Clean O2 Filter", "Prime Shields", "Upload Data", "Calibrate Distributor", "Divert Power", "Unlock Manifolds", "Submit Scan"]
    }

    # 1 common tasks shared by the whole lobby
    shared_common_task = random.choice(task_pools["common"])

    for agent in game_instance.agents:
        # 1 common, 1 long, 3 short
        if selected_config == "FIVE_MEMBER_GAME":
            agent_tasks = [shared_common_task]
            agent_tasks.append(random.choice(task_pools["long"]))
            agent_tasks.extend(random.sample(task_pools["short"], 3))

        # 7+ players
        # 1, 1, 4
        else:
           agent_tasks = [shared_common_task]
           agent_tasks.append(random.choice(task_pools["long"]))
           agent_tasks.extend(random.sample(task_pools["short"], 4))

        agent.player.ui_tasks = agent_tasks
    # Convert Agent 0 to the human
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
        return {"event": "Game not initialized"}

    try:
        await game_instance.game_step() 
        

        if game_instance.activity_log:
            last_log = str(game_instance.activity_log[-1]) 
        else:
            last_log = "Turn complete"

        return {
            "status": "Active",
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

    # Get human's assigned tasks
    personal_tasks = getattr(human_player, 'ui_tasks', [])

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
            color = agent.player.name.split()[-1].lower()
 
            # Check if the agent is alive or dead
            is_alive = getattr(agent.player, 'is_alive', True)
            players_in_room.append({
                "name": color.capitalize(),
                "color": color,
                "is_alive": is_alive
            })

    return {
        "current_room": current_room,
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

    # Who is in my room right now?
    others = {}
    for agent in game_instance.agents[1:]:
        if getattr(agent.player, 'is_alive', True):
            if agent.player.location == current_room:
                others[agent.player.name] = agent
    
    # Human executes movement
    human_player.player.location = new_room
    movement_msg = f"{human_player.player.name} moved to {new_room}"
    game_instance.activity_log.append(f"Step {game_instance.timestep}: {movement_msg}")

    # Await AI agents run
    await game_instance.game_step()

    human_player.player.location = new_room

    # Generate movement observations (X was seen leaving towards Y)
    observations = []
    for name, agent in others.items():
        if agent.player.location != current_room:
            observation_msg = f"Observation: {name.split()[-1].capitalize()} was seen leaving towards {agent.player.location}."
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

    # Who is in my room right now?
    others = {}
    for agent in game_instance.agents[1:]:
        if getattr(agent.player, 'is_alive', True):
            if agent.player.location == current_room:
                others[agent.player.name] = agent

    # Human executes action
    if hasattr(human_player.player, 'ui_tasks'):
        if task_name in human_player.player.ui_tasks:
            human_player.player.ui_tasks.remove(task_name)

    action_msg = f"{human_player.player.name} completed {task_name}"
    game_instance.activity_log.append(f"Step {game_instance.timestep}: {action_msg}")

    # Await AI agents run
    await game_instance.game_step()

    human_player.player.location = current_room

    # Generate movement observations (X was seen leaving towards Y)
    observations = []
    for name, agent in others.items():
        if agent.player.location != current_room:
            observation_msg = f"Observation: {name.split()[-1].capitalize()} was seen leaving towards {agent.player.location}."
            observations.append(observation_msg)
            game_instance.activity_log.append(f"Step {game_instance.timestep}: {observation_msg}")

    return {
        "status": "success",
        "message": action_msg,
        "timestep": game_instance.timestep,
        "observations": observations
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)