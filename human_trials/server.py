import os
import sys
import uvicorn
import networkx as nx
import re
import json
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

research_path = "/root/AmongUs/among-agents"
if research_path not in sys.path:
    sys.path.append(research_path)

from amongagents.envs.game import AmongUs
from amongagents.envs.configs.map_config import room_data, connections, vent_connections
from amongagents.envs.configs.game_config import THREE_MEMBER_GAME
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
    player_name = data.get("name", "Researcher")

    # Correct path setup
    log_dir = os.path.join(os.getcwd(), "logs")
    os.makedirs(log_dir, exist_ok=True)
    os.environ["EXPERIMENT_PATH"] = log_dir

    game_instance = AmongUs(
        game_config=THREE_MEMBER_GAME,
        agent_config={
            "Impostor": "LLM", 
            "Crewmate": "LLM",
            "IMPOSTOR_LLM_CHOICES": ["google/gemini-2.0-flash-001"], 
            "CREWMATE_LLM_CHOICES": ["google/gemini-2.0-flash-001"],
        }
    )
    game_instance.initialize_game()
    game_instance.agents[0].name = player_name

    return {
        "player_name": player_name,
        "current_room": game_instance.agents[0].player.location,
        "timestep": game_instance.timestep
    }

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

# Get current room, connected rooms, and current tasks available
@app.get("/api/room-context")
async def get_room_context():
    global game_instance
    if not game_instance:
        return {"error": "Game not initialized"}

    current_room = game_instance.agents[0].player.location

    # Get possible moves from the map logic
    possible_moves = skeld.get_adjacent_rooms(current_room)

    # Get tasks for this room
    current_tasks = room_data.get(current_room, {}).get("tasks", [])

    return {
        "current_room": current_room,
        "adjacent": possible_moves,
        "tasks": current_tasks,
        "timestep": game_instance.timestep
    }

# Handles moving
@app.post("/api/move")
async def move_player(request: Request):
    global game_instance
    data = await request.json()
    new_room = data.get("destination")
    
    if game_instance:
        game_instance.agents[0].player.location = new_room
        game_instance.timestep += 1
        game_instance.activity_log.append(f"{game_instance.agents[0].name} moved to {new_room}")

    return {
        "status": "success",
        "current_room": new_room,
        "timestep": game_instance.timestep
    }

# Handles performing a task
@app.post("/api/do-task")
async def do_task(request: Request):
    global game_instance
    data = await request.json()
    task_name = data.get("task")

    # Increment timestep
    game_instance.timestep += 1

    human_name = game_instance.agents[0].name
    message = f"{human_name} completed {task_name}"
    # Record logs so AI can see it.
    game_instance.activity_log.append(f"Step {game_instance.timestep}: {message}")
    return {
        "status": "success",
        "message": message,
        "timestep": game_instance.timestep
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)