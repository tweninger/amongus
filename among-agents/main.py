from amongagents.envs.game import AmongUs

print(f'Imports!')

from amongagents.envs.task import TaskAssignment
from amongagents.envs.configs.game_config import FIVE_MEMBER_GAME, SAMPLE_FIVE_MEMBER_GAME
from amongagents.evaluation.controlled import Interviewer
from amongagents.envs.configs.agent_config import ALL_LLM, ALL_RANDOM, CREWMATE_LLM, IMPOSTOR_LLM
from amongagents.envs.configs.map_config import map_coords
from amongagents.UI.MapUI import MapUI
from dotenv import load_dotenv
import os
import sys

print(f'Take too much time!')

sys.path.append('.')

if __name__ == "__main__":
    load_dotenv()
    if not os.getenv("OPENAI_API_KEY"):
        print("Please set OPENAI_API_KEY in .env file")
    if not os.getenv("DISPLAY"):
        print("Please set DISPLAY in .env file")
    UI = MapUI("./amongagents/assets/blankmap.png", map_coords, debug=False)
    # UI = None
    print(f'UI created! Creating game...')
    game = AmongUs(game_config=FIVE_MEMBER_GAME, include_human=False, test=False, personality=True, agent_config=ALL_LLM, UI=UI)
    # game = AmongUs(game_config=SAMPLE_FIVE_MEMBER_GAME, include_human=False, test=False, personality=True, agent_config=ALL_LLM, UI=UI)
    print(f'Game created! Running game...')
    game.run_game()