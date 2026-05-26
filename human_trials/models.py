import os
import sys
import asyncio
import networkx as nx

current_dir = os.path.dirname(os.path.abspath(__file__))
research_path = os.path.abspath(os.path.join(current_dir, "..", "among-agents"))
if research_path not in sys.path:
    sys.path.append(research_path)

from amongagents.envs.configs.map_config import room_data, connections, vent_connections
from amongagents.envs.action import Speak


class Map:
    """Handles the physical layout of the ship and connectivity."""
    def __init__(self):
        self.ship_map = nx.Graph()
        
        for room_name, details in room_data.items():
            self.ship_map.add_node(room_name, **details)

        for room1, room2 in vent_connections:
            self.ship_map.add_edge(room1, room2, connection_type="vent")

        for room1, room2 in connections:
            self.ship_map.add_edge(room1, room2, connection_type="corridor")

    def get_adjacent_rooms(self, room_name):
        if room_name not in self.ship_map:
            return []
        return [
            adj for adj, attr in self.ship_map[room_name].items()
            if attr["connection_type"] == "corridor"
        ]

# Map is a singleton
skeld = Map()

class WebPlayerAgent:
    def __init__(self, player):
        self.player = player
        self.model = "homosapiens/brain1.0"
        self.queued_action = None
        self.waiting_for_action = False # True while engine is blocking on this player's turn
        self._prev_waiting = False # Previous value, used to detect turn-start transitions

    # Called by serverHelpers when human submits an action
    async def choose_action(self, timestep):
        # Blocking loop. Pause until the human submits an action via API
        self.waiting_for_action = True
        while self.queued_action is None:
            await asyncio.sleep(0.5)
        self.waiting_for_action = False
        action = self.queued_action
        self.queued_action = None
        if action == "nudge":
            speak = Speak(current_location=self.player.location)
            speak.provide_message("...")
            return speak
        return action

    def choose_observation_location(self, map):
        return self.player.location