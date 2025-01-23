from amongagents.envs.game import AmongUs
from amongagents.envs.configs.game_config import FIVE_MEMBER_GAME, SAMPLE_FIVE_MEMBER_GAME
from amongagents.envs.configs.agent_config import ALL_LLM, ALL_RANDOM, CREWMATE_LLM, IMPOSTOR_LLM
from amongagents.envs.configs.map_config import map_coords
from amongagents.UI.MapUI import MapUI
from dotenv import load_dotenv
import os
import sys

sys.path.append('.')

# experiment logging

logs_path = './logs/'
if not os.path.exists(logs_path):
    os.makedirs(logs_path)
# all experiments are indexed with a number, so we need to find the next available number for the new experiment
experiment_number = 0
while os.path.exists(logs_path + f'exp_{experiment_number}'):
    experiment_number += 1
experiment_path = logs_path + f'exp_{experiment_number}/'
os.makedirs(experiment_path)

# create a file to store the logs
log_file = open(experiment_path + 'agent-logs.json', 'a')

# set this as a global so it can be accessed by the agents
os.environ['EXPERIMENT_PATH'] = experiment_path

if __name__ == "__main__":
    load_dotenv()
    if not os.getenv("OPENAI_API_KEY"):
        print("Please set OPENAI_API_KEY in .env file")
    if not os.getenv("DISPLAY"):
        print("Please set DISPLAY in .env file")
    UI = MapUI("./amongagents/assets/blankmap.png", map_coords, debug=False)
    # UI = None
    print(f'UI created! Creating game...')
    # game = AmongUs(game_config=FIVE_MEMBER_GAME, include_human=False, test=False, personality=True, agent_config=ALL_LLM, UI=UI)
    game = AmongUs(game_config=SAMPLE_FIVE_MEMBER_GAME, include_human=False, test=False, personality=True, agent_config=ALL_LLM, UI=UI)
    print(f'Game created! Running game...')
    game.run_game()
    print(f'Game finished! Closing UI...')
    log_file.write(']')