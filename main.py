# !/usr/bin/env python3
# usage: main.py [-h] [--name NAME] 

import os
import sys

# Add among-agents package to the path
sys.path.append(os.path.join(os.path.abspath("."), "among-agents"))

import argparse
import datetime
import subprocess

from amongagents.envs.configs.agent_config import ALL_LLM
from amongagents.envs.configs.game_config import FIVE_MEMBER_GAME, SEVEN_MEMBER_GAME
from amongagents.envs.configs.map_config import map_coords
from amongagents.envs.game import AmongUs
from amongagents.UI.MapUI import MapUI
from dotenv import load_dotenv

# Import necessary modules

# Constants
ROOT_PATH = os.path.abspath(".")
LOGS_PATH = os.path.join(ROOT_PATH, "expt-logs")
ASSETS_PATH = os.path.join(ROOT_PATH, "among-agents", "amongagents", "assets")
BLANK_MAP_IMAGE = os.path.join(ASSETS_PATH, "blankmap.png")

# Initialize environment variables
load_dotenv()

# Get experiment date and Git commit hash
DATE = datetime.datetime.now().strftime("%Y-%m-%d")
COMMIT_HASH = (
    subprocess.check_output(["git", "rev-parse", "HEAD"]).strip().decode("utf-8")
)

# Default experiment arguments
DEFAULT_ARGS = {
    "game_config": FIVE_MEMBER_GAME,
    "include_human": False,
    "test": False,
    "personality": False,
    "agent_config": ALL_LLM,
    "UI": False,
}

def setup_experiment(experiment_name=None):
    """Set up experiment directory and files."""
    os.makedirs(LOGS_PATH, exist_ok=True)

    if not experiment_name:
        experiment_number = 0
        while os.path.exists(os.path.join(LOGS_PATH, f"{DATE}_exp_{experiment_number}")):
            experiment_number += 1
        experiment_name = f"{DATE}_exp_{experiment_number}"
    else:
        experiment_name = f"{DATE}_{experiment_name}"

    experiment_path = os.path.join(LOGS_PATH, experiment_name)
    os.makedirs(experiment_path, exist_ok=True)
    
    # delete everything in the experiment path
    for file in os.listdir(experiment_path):
        os.remove(os.path.join(experiment_path, file))

    with open(
        os.path.join(experiment_path, "experiment-details.txt"), "w"
    ) as experiment_file:
        experiment_file.write(f"Experiment {experiment_path}\n")
        experiment_file.write(f"Date: {DATE}\n")
        experiment_file.write(f"Commit: {COMMIT_HASH}\n")
        experiment_file.write(f"Experiment args: {DEFAULT_ARGS}\n")
        experiment_file.write(f"Path of executable file: {os.path.abspath(__file__)}\n")

    os.environ["EXPERIMENT_PATH"] = experiment_path

def game(experiment_name=None, game_index=None):
    """Run the game."""
    setup_experiment(experiment_name)
    ui = MapUI(BLANK_MAP_IMAGE, map_coords, debug=False) if DEFAULT_ARGS["UI"] else None
    print("UI created! Creating game..." if ui else "No UI selected. Running game without UI.")
    game_instance = AmongUs(
        game_config=DEFAULT_ARGS["game_config"],
        include_human=DEFAULT_ARGS["include_human"],
        test=DEFAULT_ARGS["test"],
        personality=DEFAULT_ARGS["personality"],
        agent_config=DEFAULT_ARGS["agent_config"],
        UI=ui,
        game_index=game_index,
    )
    print("Game created! Running game...")
    game_instance.run_game()
    print("Game finished! Closing UI...")

def multiple_games(experiment_name=None, num_games=1):
    """Run multiple games and log the results."""
    setup_experiment(experiment_name)
    for i in range(1, num_games+1):
        print(f"Running game {i}...")
        ui = MapUI(BLANK_MAP_IMAGE, map_coords, debug=False) if DEFAULT_ARGS["UI"] else None
        game_instance = AmongUs(
            game_config=DEFAULT_ARGS["game_config"],
            include_human=DEFAULT_ARGS["include_human"],
            test=DEFAULT_ARGS["test"],
            personality=DEFAULT_ARGS["personality"],
            agent_config=DEFAULT_ARGS["agent_config"],
            UI=ui,
            game_index=i,
        )
        game_instance.run_game()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run an AmongUs experiment.")
    parser.add_argument(
        "--name", type=str, default=None, help="Optional name for the experiment."
    )
    args = parser.parse_args()
    # game(experiment_name=args.name)
    multiple_games(experiment_name=args.name, num_games=2)