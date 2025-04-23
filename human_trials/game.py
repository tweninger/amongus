#!/usr/bin/env python3

import os
import sys
import asyncio
from typing import List
import datetime
import subprocess
import uuid
import threading
import random

sys.path.append(os.path.join(os.path.abspath(".."), "among-agents"))
sys.path.append(os.path.abspath(".."))

from amongagents.envs.configs.game_config import FIVE_MEMBER_GAME, SEVEN_MEMBER_GAME, THREE_MEMBER_GAME
from amongagents.envs.game import AmongUs
from dotenv import load_dotenv

from utils import setup_experiment
from config import CONFIG

ROOT_PATH = os.path.abspath(".")
LOGS_PATH = os.path.join(ROOT_PATH, CONFIG["logs_path"])

load_dotenv()

experiment_name = CONFIG["experiment_name"]

# Define the list of models for tournament style
BIG_LIST_OF_MODELS: List[str] = [
    "microsoft/phi-4",
    "anthropic/claude-3.5-sonnet",
    "anthropic/claude-3.7-sonnet:thinking",
    "openai/o3-mini-high",
    "openai/gpt-4o-mini",
    "deepseek/deepseek-r1-distill-llama-70b",
    "qwen/qwen-2.5-7b-instruct",
    "mistralai/mistral-7b-instruct",
    "deepseek/deepseek-r1",
    "meta-llama/llama-3.3-70b-instruct",
    "google/gemini-2.0-flash-001",
]

# Game configuration
GAME_ARGS = {
    "game_config": FIVE_MEMBER_GAME,
    "include_human": True,  # Set to True for human players
    "test": False,
    "personality": False,
    "agent_config": {
        "Impostor": "LLM",
        "Crewmate": "LLM",
        # "IMPOSTOR_LLM_CHOICES": BIG_LIST_OF_MODELS,
        # "CREWMATE_LLM_CHOICES": BIG_LIST_OF_MODELS,
        "IMPOSTOR_LLM_CHOICES": ["meta-llama/llama-3.3-70b-instruct"],
        "CREWMATE_LLM_CHOICES": ["meta-llama/llama-3.3-70b-instruct"],
    },
    "UI": False,
    "Streamlit": False,  # Set to False for command line
    "tournament_style": "random",  # Default tournament style
}

def setup_experiment_once():
    """Setup experiment only once"""
    # Check if experiment directory already exists
    experiment_dir = os.path.join(LOGS_PATH, experiment_name)
    if os.path.exists(experiment_dir):
        return
    
    print(f"Setting up experiment {experiment_name}")
    setup_experiment(experiment_name, LOGS_PATH, CONFIG["date"], CONFIG["commit_hash"], GAME_ARGS)

def get_next_game_index():
    """Get the next game index by reading the experiment log file"""
    # Check if EXPERIMENT_PATH is set
    if "EXPERIMENT_PATH" not in os.environ:
        # If not set, return default index of 1
        return 1
        
    experiment_file_path = os.path.join(os.environ["EXPERIMENT_PATH"], "experiment-details.txt")
    
    # Default to 1 if file doesn't exist or no games found
    next_index = 1
    
    if os.path.exists(experiment_file_path):
        with open(experiment_file_path, 'r') as file:
            content = file.read()
            # Look for "Game X started" entries
            import re
            game_entries = re.findall(r'Game (\d+) started', content)
            if game_entries:
                # Get the highest game index and increment by 1
                next_index = max(map(int, game_entries)) + 1
    
    return next_index

async def run_game_with_index():
    """Run a single game with an incremented game index."""
    # Ensure setup has been done before trying to get next game index
    setup_experiment_once()
        
    # Get the next game index
    game_index = get_next_game_index()
    
    # Append game index to the experiment details
    with open(os.path.join(os.environ["EXPERIMENT_PATH"], "experiment-details.txt"), "a") as experiment_file:
        experiment_file.write(f"\nGame {game_index} started.\n")

    async def run_limited_game():
        # Get tournament style from command line args or default to "random"
        tournament_style = GAME_ARGS["tournament_style"]
        
        # Prepare agent config based on tournament style
        agent_config = GAME_ARGS["agent_config"].copy()
        
        if tournament_style == "1on1":
            # Randomly select one model for each role for this specific game
            agent_config["CREWMATE_LLM_CHOICES"] = [random.choice(BIG_LIST_OF_MODELS)]
            agent_config["IMPOSTOR_LLM_CHOICES"] = [random.choice(BIG_LIST_OF_MODELS)]
        
        game = AmongUs(
            game_config=GAME_ARGS["game_config"],
            include_human=GAME_ARGS["include_human"],
            test=GAME_ARGS["test"],
            personality=GAME_ARGS["personality"],
            agent_config=agent_config,
            UI=None,  # No UI
            game_index=game_index,
        )
        await game.run_game()
        return game.summary_json  # Return the game summary

    # Run a single game
    return await run_limited_game()

def main():
    print("Starting Among Us: A Sandbox for Agentic Deception")
    print("Running game simulation...")

    # Run the game
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    game_results = loop.run_until_complete(run_game_with_index())
    loop.close()
    
    print("\nGame completed!")
    print("Game results:", game_results)

if __name__ == "__main__":
    main()