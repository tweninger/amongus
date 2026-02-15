import os
import sys
import uvicorn
import random # just for proof of concept
import networkx as nx
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

research_path = "/root/AmongUs/among-agents"
if research_path not in sys.path:
    sys.path.append(research_path)
    
from amongagents.envs.configs.map_config import room_data, connections, vent_connections
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
game_state = {
    "player_name": "Unknown",
    "status": "Lobby",
    "current_room": "Cafeteria",
    "timestep": 0
}

# Index
@app.get("/")
async def serve_game():
    return FileResponse("templates/game.html")

# Receive player name from frontend, updates global game state, and returns initialized state to session.
@app.post("/api/join")
async def join_game(request: Request):
    data = await request.json()
    player_name = data.get("name", "Player 1")

    # Init game state 
    game_state["player_name"] = player_name 
    game_state["status"] = "Ready"
    print(f"{player_name} has entered the lobby")

    return game_state

# Proof of concept for getting status
# Returns something for now
@app.get("/api/status")
async def get_status():
    events = [
        "Blue is moving to Navigations",
        "Red is doing tasks in Electrical",
        "Yellow is standing in the Cafeteria",
        "Green just entered the Security room"
    ]
    return {
        "status": game_state["status"],
        "event": random.choice(events)
    }

# Get current room, connected rooms, and current tasks available
@app.get("/api/room-context")
async def get_room_context():
    # Get current room of player
    current_room = game_state["current_room"]

    # Get possible moves
    possible_moves = skeld.get_adjacent_rooms(current_room)

    current_tasks = room_data[current_room]["tasks"]

    return {
        "current_room": current_room,
        "adjacent": possible_moves,
        "tasks": current_tasks,
        "timestep": game_state["timestep"]
    }

# Handles moving
@app.post("/api/move")
async def move_player(request: Request):
    data = await request.json()
    new_room = data.get("destination")
    
    # Update the master state
    game_state["current_room"] = new_room
    game_state["timestep"] += 1 # Moving takes a timestep

    
    # Return the new list of where they can go next
    return {
        "status": "success",
        "current_room": new_room,
        "adjacent": skeld.get_adjacent_rooms(new_room),
        "timestep": game_state["timestep"]
    }

# Handles performing a task
@app.post("/api/do-task")
async def do_task(request: Request):
    data = await request.json()
    task_name = data.get("task")

    game_state["timestep"] += 1 # Performing a task takes a timestep

    message = f"{game_state['player_name']} completed {task_name}"
    return {
        "status": "success",
        "message": message,
        "timestep": game_state["timestep"]
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)