# !/usr/bin/env python3
# usage: main.py [-h] [--name NAME]

import os
import sys
import asyncio

from typing import Optional, List

# add among-agents package to the path
sys.path.append(os.path.join(os.path.abspath("."), "among-agents"))

import argparse
import datetime
import subprocess

from amongagents.envs.configs.agent_config import ALL_LLM
from amongagents.envs.configs.game_config import FIVE_MEMBER_GAME, SEVEN_MEMBER_GAME, SAMPLE_FIVE_MEMBER_GAME
from amongagents.envs.configs.map_config import map_coords
from amongagents.envs.game import AmongUs
from amongagents.UI.MapUI import MapUI
from dotenv import load_dotenv

from utils import setup_experiment

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
ARGS = {
    "game_config": SEVEN_MEMBER_GAME,
    # "game_config": FIVE_MEMBER_GAME,
    "include_human": False,
    "test": False,
    "personality": False,
    "agent_config": {
        "Impostor": "LLM", 
        "Crewmate": "LLM",    
        "IMPOSTOR_LLM_CHOICES": ["meta-llama/llama-3.3-70b-instruct"],
        # "CREWMATE_LLM_CHOICES": ["microsoft/phi-4"],
        "CREWMATE_LLM_CHOICES": ["meta-llama/llama-3.3-70b-instruct"],
        # "IMPOSTOR_LLM_CHOICES": ["microsoft/phi-4"],
        # "IMPOSTOR_LLM_CHOICES": ["deepseek/deepseek-r1-distill-llama-70b"],
        # "CREWMATE_LLM_CHOICES": ["deepseek/deepseek-r1-distill-llama-70b"],
    },
    "UI": True,
    # "UI": False,
}

async def multiple_games(experiment_name=None, num_games=1):
    setup_experiment(experiment_name, LOGS_PATH, DATE, COMMIT_HASH, ARGS)
    ui = MapUI(BLANK_MAP_IMAGE, map_coords, debug=False) if ARGS["UI"] else None
    with open(os.path.join(os.environ["EXPERIMENT_PATH"], "experiment-details.txt"), "a") as experiment_file:
        experiment_file.write(f"\nExperiment args: {ARGS}\n")
    tasks = [
        AmongUs(
            game_config=ARGS["game_config"],
            include_human=ARGS["include_human"],
            test=ARGS["test"],
            personality=ARGS["personality"],
            agent_config=ARGS["agent_config"],
            UI=ui,
            game_index=i,
        ).run_game()
        for i in range(1, num_games+1)
    ]
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run an AmongUs experiment.")
    parser.add_argument("--name", type=str, default=None, help="Optional name for the experiment.")
    parser.add_argument("--num_games", type=int, default=1, help="Number of games to run.")
    args = parser.parse_args()
    asyncio.run(multiple_games(experiment_name=args.name, num_games=args.num_games))