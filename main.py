import os
import sys
import os
import sys
import subprocess
sys.path.append(os.path.abspath(".") + "/among-agents/") # import the among-agents package

from amongagents.envs.game import AmongUs
from amongagents.envs.configs.game_config import FIVE_MEMBER_GAME, SAMPLE_FIVE_MEMBER_GAME
from amongagents.envs.configs.agent_config import ALL_LLM, ALL_RANDOM, CREWMATE_LLM, IMPOSTOR_LLM
from amongagents.envs.configs.map_config import map_coords
from amongagents.UI.MapUI import MapUI

from dotenv import load_dotenv
import os

root_path = os.path.abspath(".")

# get the date of the experiment
import datetime
now = datetime.datetime.now()
date = now.strftime("%Y-%m-%d")

# git HEAD commit
commit = subprocess.check_output(['git', 'rev-parse', 'HEAD']).strip().decode('utf-8')

args = {
    'game_config': FIVE_MEMBER_GAME,
    'include_human': False,
    'test': False,
    'personality': True,
    'agent_config': ALL_LLM,
    'UI': None
}

# experiment logging

logs_path = root_path + '/expt-logs/'
if not os.path.exists(logs_path):
    os.makedirs(logs_path)
# all experiments are indexed with a number, so we need to find the next available number for the new experiment

expt_name = None

if not expt_name:
    experiment_number = 0
    while os.path.exists(logs_path + f'exp_{experiment_number}'):
        experiment_number += 1
    expt_path = logs_path + f'{date}_exp_{experiment_number}/'
else:
    expt_path = logs_path + f'{date}_{expt_name}/'

os.makedirs(expt_path)

# create a file to store the logs
log_file = open(expt_path + 'agent-logs.json', 'a')

# create a file to store the experiment details
experiment_file = open(expt_path + 'experiment-details.txt', 'w')
experiment_file.write(f'Experiment {expt_path}\n')
experiment_file.write(f'Date: {date}\n')
experiment_file.write(f'Commit: {commit}\n')
experiment_file.write(f'Experiment args: {args}\n')
experiment_file.write(f'Path of executable file: {os.path.abspath(__file__)}\n')
# flush
experiment_file.close()

# set this as a global so it can be accessed by the agents
os.environ['EXPERIMENT_PATH'] = expt_path

load_dotenv()
if not os.getenv("OPENAI_API_KEY"):
    print("Please set OPENAI_API_KEY in .env file")
if not os.getenv("DISPLAY"):
    print("Please set DISPLAY in .env file")

def game():
    UI = MapUI(f"{root_path}/among-agents/amongagents/assets/blankmap.png", map_coords, debug=False)
    # UI = None
    print(f'UI created! Creating game...')
    game = AmongUs(game_config=FIVE_MEMBER_GAME, include_human=False, test=False, personality=True, agent_config=ALL_LLM, UI=UI)
    print(f'Game created! Running game...')
    game.run_game()
    print(f'Game finished! Closing UI...')
    log_file.write(']')

if __name__ == "__main__":
    game()