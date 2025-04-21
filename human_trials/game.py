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
        "IMPOSTOR_LLM_CHOICES": BIG_LIST_OF_MODELS,
        "CREWMATE_LLM_CHOICES": BIG_LIST_OF_MODELS,
    },
    "UI": False,
    "Streamlit": True,  # Set to True for Streamlit UI
    "tournament_style": "random",  # Default tournament style
}

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
    if "experiment_setup" not in st.session_state:
        st.session_state.experiment_setup = True
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
    if not st.session_state.experiment_setup:
        setup_experiment_once()
        
    # Get the next game index
    game_index = get_next_game_index()
    
    # Append game index to the experiment details
    with open(os.path.join(os.environ["EXPERIMENT_PATH"], "experiment-details.txt"), "a") as experiment_file:
        experiment_file.write(f"\nGame {game_index} started.\n")

    async def run_limited_game():
        # Get tournament style from session state or default to "random"
        tournament_style = st.session_state.get("tournament_style", "random")
        
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
            UI=None,  # No UI, using Streamlit instead
            game_index=game_index,
        )
        await game.run_game()
        return game.summary_json  # Return the game summary

    # Run a single game
    return await run_limited_game()

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
    
    # Initialize tournament style in session state
    if "tournament_style" not in st.session_state:
        st.session_state.tournament_style = GAME_ARGS["tournament_style"]
    
    # Setup experiment only if not already done
    if not st.session_state.experiment_setup:
        setup_experiment_once()
    
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
    
    # App title
    st.title("Among Us: A Sandbox for Agentic Deception")
    
    # Tournament style selection
    st.sidebar.header("Game Settings")
    tournament_style = st.sidebar.radio(
        "Tournament Style",
        options=["random", "1on1"],
        index=0 if st.session_state.tournament_style == "random" else 1,
        help="Random: All models are randomly selected. 1on1: One model is randomly selected for each role."
    )
    st.session_state.tournament_style = tournament_style
    
    # Initialize session state for game results and updates
    if "game_results" not in st.session_state:
        st.session_state.game_results = None
    if "game_updates" not in st.session_state:
        st.session_state.game_updates = []
    if "update_placeholder" not in st.session_state:
        st.session_state.update_placeholder = st.empty()
    if "update_counter" not in st.session_state:
        st.session_state.update_counter = 0
    
    # Create a container for the message display
    message_container = st.container()

    # Check if experiment is properly set up
    if "EXPERIMENT_PATH" not in os.environ:
        st.error("Experiment setup failed. Please refresh the page.")
        return

    if st.session_state.game_results is None:
        st.write("Click the button below to run a single game simulation.")
        
        # Add collapsible container for Skeld map
        with st.expander("View The Skeld Map", expanded=False):
            st.image(os.path.join(CONFIG["assets_path"], "skeld.png"), width=600, use_container_width=False)

        # Display game updates in a scrollable container
        with message_container:
            if st.session_state.game_updates:
                st.subheader("Game Updates")
                # Use a text area for updates instead of HTML
                updates_text = "\n".join([f"{datetime.datetime.now().strftime('%H:%M:%S')} - {msg}" for msg in st.session_state.game_updates])
                st.text_area("Game Updates", value=updates_text, height=150, key="game_updates_display", label_visibility="collapsed")

        if st.button("Run Game"):
            # Create a placeholder for live updates
            updates_placeholder = st.empty()
            st.session_state.update_placeholder = updates_placeholder
            
            def update_display():
                # Increment the counter to create a unique key
                st.session_state.update_counter += 1
                unique_key = f"live_updates_display_{st.session_state.update_counter}"
                
                # Update the display with current game updates
                with updates_placeholder.container():
                    st.subheader("Game Updates")
                    # Use a text area for updates instead of HTML
                    updates_text = "\n".join([f"{msg}" for msg in st.session_state.game_updates])
                    st.text_area("Game Updates", value=updates_text, height=150, key=unique_key, label_visibility="collapsed")
            
            with st.spinner("Running game simulation..."):
                # Set up initial display
                update_display()
                
                # Run the game
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                game_results = loop.run_until_complete(run_game_with_index())
                loop.close()
                
                # Final update of display
                update_display()
                
                st.session_state.game_results = game_results
                st.rerun()
    else:
        # Display game results
        st.header("Game Results")
        
        # Extract game number and model information
        game_number = list(st.session_state.game_results.keys())[0]
        st.subheader(f"Game: {game_number}")
        
        # Display tournament style
        st.write(f"Tournament Style: {st.session_state.tournament_style}")
        
        # Display model information based on tournament style
        if st.session_state.tournament_style == "1on1":
            st.write(f"Crewmate Model: {GAME_ARGS['agent_config']['CREWMATE_LLM_CHOICES'][0]}")
            st.write(f"Impostor Model: {GAME_ARGS['agent_config']['IMPOSTOR_LLM_CHOICES'][0]}")
        else:
            st.write(f"Models used: {', '.join(GAME_ARGS['agent_config']['IMPOSTOR_LLM_CHOICES'])}")
        
        # Display winner reason - handle potential JSON parsing error
        try:
            winner_reason = st.session_state.game_results[game_number]["winner_reason"]
            if isinstance(winner_reason, str):
                st.write("Winner Reason:")
                st.write(winner_reason)
            else:
                st.json(winner_reason)
        except Exception as e:
            st.write("Winner Reason:")
            st.write(st.session_state.game_results[game_number]["winner_reason"])
        
        # Display game updates in a scrollable container
        with message_container:
            if st.session_state.game_updates:
                st.subheader("Game Updates")
                # Use a text area for updates instead of HTML
                updates_text = "\n".join([f"{msg}" for msg in st.session_state.game_updates])
                st.text_area("Game Updates", value=updates_text, height=150, key="game_updates_display", label_visibility="collapsed")
        
        # Add button to run another game
        if st.button("Run Another Game"):
            st.session_state.game_results = None
            # Clear game updates to start fresh
            st.session_state.game_updates = []
            st.rerun()
            
        # Comment about extending functionality
        st.markdown("""
        ---
        **Developer Note:** 
        
        To show more detailed information from the AmongUs game on this Streamlit app:
        1. Modify the AmongUs class in `amongagents/envs/game.py` to expose more data
        2. Consider adding a callback mechanism to update Streamlit in real-time
        3. Extend the `summary_json` object to include more game details
        4. You might need to create a custom UI handler that works with Streamlit
        """)

if __name__ == "__main__":
    main() 