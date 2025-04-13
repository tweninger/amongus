import os
import sys
import asyncio
import streamlit as st
from typing import List
import datetime
import subprocess

sys.path.append(os.path.join(os.path.abspath(".."), "among-agents"))
sys.path.append(os.path.abspath(".."))

from amongagents.envs.configs.game_config import FIVE_MEMBER_GAME, SEVEN_MEMBER_GAME, THREE_MEMBER_GAME
from amongagents.envs.game import AmongUs
from dotenv import load_dotenv

from utils import setup_experiment

ROOT_PATH = os.path.abspath(".")
LOGS_PATH = os.path.join(ROOT_PATH, "expt-logs")

# Initialize environment variables
load_dotenv()

# Get experiment date and Git commit hash
DATE = datetime.datetime.now().strftime("%Y-%m-%d")
COMMIT_HASH = (
    subprocess.check_output(["git", "rev-parse", "HEAD"]).strip().decode("utf-8")
)

# Default experiment arguments
ARGS = {
    "game_config": THREE_MEMBER_GAME,
    "include_human": False,
    "test": False,
    "personality": False,
    "agent_config": {
        "Impostor": "LLM", 
        "Crewmate": "LLM",    
        "IMPOSTOR_LLM_CHOICES": ["meta-llama/llama-3.3-70b-instruct"],
        "CREWMATE_LLM_CHOICES": ["meta-llama/llama-3.3-70b-instruct"],
    },
    "UI": False,  # Disable UI since we're using Streamlit
}

async def run_single_game():
    setup_experiment("streamlit_game", LOGS_PATH, DATE, COMMIT_HASH, ARGS)
    with open(os.path.join(os.environ["EXPERIMENT_PATH"], "experiment-details.txt"), "a") as experiment_file:
        experiment_file.write(f"\nExperiment args: {ARGS}\n")

    # Create semaphore to limit concurrent games (keeping the structure even though we only run one game)
    semaphore = asyncio.Semaphore(1)

    async def run_limited_game(game_index):
        async with semaphore:
            game = AmongUs(
                game_config=ARGS["game_config"],
                include_human=ARGS["include_human"],
                test=ARGS["test"],
                personality=ARGS["personality"],
                agent_config=ARGS["agent_config"],
                UI=None,  # No UI, using Streamlit instead
                game_index=game_index,
            )
            await game.run_game()
            return game.summary_json  # Return the game summary

    # Run a single game
    return await run_limited_game(1)

def main():
    # Set page config (must be first Streamlit command)
    st.set_page_config(
        page_title="Among Us (Deception Sandbox)",
        page_icon="🚀",
        layout="centered"
    )
    
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

    if st.session_state.game_results is None:
        st.write("Click the button below to run a single game simulation.")
        
        # Add collapsible container for Skeld map
        with st.expander("View The Skeld Map", expanded=False):
            st.image("assets/skeld.png", width=600, use_container_width=False)

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
                game_results = loop.run_until_complete(run_single_game())
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
        
        st.write("Model used: meta-llama/llama-3.3-70b-instruct")
        
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