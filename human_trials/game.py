# !/usr/bin/env python3
# usage: streamlit run game.py

import os
import sys
import asyncio
import streamlit as st
from typing import List
import datetime
import subprocess
import uuid
import threading
import random
import json
import time
import signal
import io
import contextlib

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

TESTING_MODELS = [
    "meta-llama/llama-3.3-70b-instruct",
]

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
        "IMPOSTOR_LLM_CHOICES": TESTING_MODELS,
        "CREWMATE_LLM_CHOICES": TESTING_MODELS,
    },
    "UI": False,
    "Streamlit": True,  # Set to True for Streamlit UI
    "tournament_style": "random",  # Default tournament style
}

# Path to the game state file that persists between Streamlit refreshes
GAME_STATE_FILE = os.path.join(ROOT_PATH, "game_state.json")

# Context manager to suppress stderr
@contextlib.contextmanager
def suppress_stderr():
    stderr = sys.stderr
    sys.stderr = io.StringIO()
    try:
        yield
    finally:
        sys.stderr = stderr

def setup_experiment_once():
    """Setup experiment only once during the Streamlit session"""
    # Check if experiment directory already exists
    experiment_dir = os.path.join(LOGS_PATH, experiment_name)
    if os.path.exists(experiment_dir):
        # If directory exists, just set the flag and return
        if "experiment_setup" not in st.session_state:
            st.session_state.experiment_setup = True
        return
    
    # Only run setup if not already done in this session
    if not os.environ.get("EXPERIMENT_PATH"):
        os.environ["EXPERIMENT_PATH"] = experiment_dir
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

# Global variable to hold the game instance
GAME_INSTANCE = None

def save_game_state(game):
    """Save the current game state to a file for persistence across Streamlit refreshes"""
    # Create a simple state object with essential game information
    state = {
        "game_index": game.game_index,
        "timestep": game.timestep,  # The timestep attribute is initialized in initialize_game method
        "running": True,
        "last_update": time.time()
    }
    
    # Write to the state file
    with open(GAME_STATE_FILE, "w") as f:
        json.dump(state, f)

def load_game_state():
    """Load the game state from file"""
    if os.path.exists(GAME_STATE_FILE):
        try:
            with open(GAME_STATE_FILE, "r") as f:
                return json.load(f)
        except:
            return None
    return None

async def run_game_instance():
    """Run a single game instance that persists across Streamlit refreshes"""
    global GAME_INSTANCE
    
    # Check if we already have a game running
    state = load_game_state()
    
    if GAME_INSTANCE is None:
        # Ensure setup has been done before starting a new game
        if not os.environ.get("EXPERIMENT_PATH"):
            setup_experiment_once()
            
        # Get the next game index
        game_index = get_next_game_index()
        
        # Append game index to the experiment details
        with open(os.path.join(os.environ["EXPERIMENT_PATH"], "experiment-details.txt"), "a") as experiment_file:
            experiment_file.write(f"\nGame {game_index} started.\n")
        
        # Create a new game instance
        GAME_INSTANCE = AmongUs(
            game_config=GAME_ARGS["game_config"],
            include_human=GAME_ARGS["include_human"],
            test=GAME_ARGS["test"],
            personality=GAME_ARGS["personality"],
            agent_config=GAME_ARGS["agent_config"],
            UI=None,  # No UI, using Streamlit instead
            game_index=game_index,
        )
        
        # Initialize the game before saving state
        GAME_INSTANCE.initialize_game()
        
        # Save initial game state
        save_game_state(GAME_INSTANCE)
        
        # Start the game in a separate thread with stderr suppression
        def run_game_with_suppression():
            with suppress_stderr():
                asyncio.run(GAME_INSTANCE.run_game())
                
        threading.Thread(target=run_game_with_suppression, daemon=True).start()
    
    # Always return the current game instance
    return GAME_INSTANCE

def main():
    # Set page config (must be first Streamlit command)
    st.set_page_config(
        page_title="Among Us (Deception Sandbox)",
        page_icon="🚀",
        layout="centered"
    )
    
    # Initialize session state for experiment setup
    if "experiment_setup" not in st.session_state:
        st.session_state.experiment_setup = False
    
    # Setup experiment only if not already done
    if not st.session_state.experiment_setup:
        setup_experiment_once()
    
    # Get or create the game instance
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    game = loop.run_until_complete(run_game_instance())
    
    # Check if the game has been initialized
    if not hasattr(game, 'timestep'):
        st.warning("Game is initializing. Please wait...")
        st.stop()
    
    # Custom styling
    st.markdown("""
    <style>
    .main {
        padding: 2rem;
    }
    .stButton button {
        width: 100%;
    }
    </style>
    """, unsafe_allow_html=True)
    
    # Inject custom CSS to set the width of the sidebar
    st.markdown(
        """
        <style>
            section[data-testid="stSidebar"] {
                width: 500px !important; # Set the width to your desired value
            }
        </style>
        """,
        unsafe_allow_html=True,
    )
    
    # App title
    st.title("Among Us: A Sandbox for Agentic Deception")
    
    # Load the game state
    game_state = load_game_state()
    
    # Display game state
    if game_state:
        st.header(f"Game {game_state['game_index']} - Step {game_state['timestep']}")
        
        # Calculate time since last update
        last_update = game_state.get('last_update', 0)
        elapsed = time.time() - last_update
        st.write(f"Last update: {elapsed:.1f} seconds ago")
        
        # Auto-refresh if the game state has changed
        if "last_timestep" not in st.session_state:
            st.session_state.last_timestep = game_state['timestep']
        elif st.session_state.last_timestep != game_state['timestep']:
            st.session_state.last_timestep = game_state['timestep']
            st.rerun()
    
    # Instructions in sidebar
    st.sidebar.header("Game Instructions")
    st.sidebar.markdown("""
    ## How to Play Among Us
    
    **Game Phases:**
    1. **Task Phase**: Move around the ship, complete tasks, and gather information
    2. **Meeting Phase**: Discuss with other players and vote out suspected Impostors
    
    **Actions Available:**
    - **Move**: Navigate between rooms
    - **Complete Task**: Finish assigned tasks (Crewmates only)
    - **Call Meeting**: Trigger an emergency meeting
    - **Speak**: Communicate with other players
    - **Vote**: Choose who to eject during meetings
    - **Kill**: Eliminate a player (Impostors only)
    - **Use Vent**: Travel through vents (Impostors only)
    - **Sabotage**: Create chaos (Impostors only)
    
    **Win Conditions:**
    - **Crewmates**: Complete all tasks or eject all Impostors
    - **Impostors**: Eliminate enough Crewmates to equal their number
    """)
    
    # Display Skeld map
    with st.expander("View The Skeld Map", expanded=False):
        st.image(os.path.join(CONFIG["assets_path"], "skeld.png"), width=600, use_container_width=False)
    
    # Add a placeholder for game updates
    if "update_placeholder" not in st.session_state:
        st.session_state.update_placeholder = st.empty()
    
    # The game is running in a separate thread, so we just need to display its state
    st.header("Game is Running")
    st.write("The game is running and waiting for human input. If it's your turn to act, you'll see an interface below.")
    
    # Auto-refresh the page periodically to check for game state updates
    time.sleep(1)  # Small delay to prevent excessive CPU usage
    st.rerun()

if __name__ == "__main__":
    main() 