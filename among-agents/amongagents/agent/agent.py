import ast
import json
import os
import random
import re
from datetime import datetime
from typing import Any
import aiohttp
import streamlit as st
import time

import numpy as np
import requests
import asyncio
from amongagents.agent.neutral_prompts import *

class Agent:
    def __init__(self, player):
        self.player = player

    def respond(self, message):
        return "..."

    def choose_action(self):
        return None


class LLMAgent(Agent):
    def __init__(self, player, tools, game_index, agent_config, list_of_impostors):
        super().__init__(player)
        if player.identity == "Crewmate":
            system_prompt = CREWMATE_PROMPT.format(name=player.name)
            if player.personality is not None:
                system_prompt += PERSONALITY_PROMPT.format(
                    personality=CrewmatePersonalities[player.personality]
                )
            system_prompt += CREWMATE_EXAMPLE
            model = random.choice(agent_config["CREWMATE_LLM_CHOICES"])
        elif player.identity == "Impostor":
            system_prompt = IMPOSTOR_PROMPT.format(name=player.name)
            if player.personality is not None:
                system_prompt += PERSONALITY_PROMPT.format(
                    personality=ImpostorPersonalities[player.personality]
                )
            system_prompt += IMPOSTOR_EXAMPLE
            system_prompt += f"List of impostors: {list_of_impostors}"
            model = random.choice(agent_config["IMPOSTOR_LLM_CHOICES"])

        self.system_prompt = system_prompt
        self.model = model
        self.temperature = 0.7
        self.api_key = os.getenv("OPENROUTER_API_KEY")
        self.api_url = "https://openrouter.ai/api/v1/chat/completions"
        self.summarization = "No thought process has been made."
        self.processed_memory = "No memory has been processed."
        self.chat_history = []
        self.tools = tools
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.log_path = os.getenv("EXPERIMENT_PATH") + "/agent-logs.json"
        self.compact_log_path = os.getenv("EXPERIMENT_PATH") + "/agent-logs-compact.json"
        self.game_index = game_index

    def log_interaction(self, sysprompt, prompt, original_response, step):
        """
        Helper method to store model interactions in properly nested JSON format.
        Handles deep nesting and properly parses all string-formatted dictionaries.

        Args:
            prompt (str): The input prompt containing dictionary-like strings
            response (str): The model response containing bracketed sections
            step (str): The game step number
        """

        def parse_dict_string(s):
            if isinstance(s, str):
                # Replace any single quotes with double quotes for valid JSON
                s = s.replace("'", '"')
                s = s.replace('"', '"')
                # Properly escape newlines for JSON
                s = s.replace("\\n", "\\\\n")
                try:
                    # Try parsing as JSON first
                    try:
                        return json.loads(s)
                    except json.JSONDecodeError:
                        # If JSON parsing fails, try ast.literal_eval
                        return ast.literal_eval(s)
                except:
                    # If parsing fails, keep original string
                    return s
            return s

        def extract_action(text):
            """Extract action from response text."""
            if "[Action]" in text:
                action_parts = text.split("[Action]")
                thought = action_parts[0].strip()
                action = action_parts[1].strip()
                return {"thought": thought, "action": action}
            return text

        # Parse the prompt
        if isinstance(prompt, str):
            try:
                prompt = parse_dict_string(prompt)
            except:
                pass
        if isinstance(original_response, str):
            sections = {}
            current_section = None
            current_content = []

            for line in original_response.split("\n"):
                line = line.strip()
                if line.startswith("[") and line.endswith("]"):
                    if current_section:
                        sections[current_section] = " ".join(current_content).strip()
                        current_content = []
                    current_section = line[1:-1]  # Remove brackets
                elif line and current_section:
                    current_content.append(line)

            if current_section and current_content:
                sections[current_section] = " ".join(current_content).strip()

            new_response = sections if sections else original_response

            # Parse any dictionary strings in the response sections and handle [Action]
            if isinstance(new_response, dict):
                for key, value in new_response.items():
                    if isinstance(value, str):
                        new_response[key] = extract_action(value)
                    else:
                        new_response[key] = parse_dict_string(value)

        # Create the interaction object with proper nesting
        interaction = {
            'game_index': 'Game ' + str(self.game_index),
            'step': step,
            "timestamp": str(datetime.now()),
            "player": {"name": self.player.name, "identity": self.player.identity, "personality": self.player.personality, "model": self.model, "location": self.player.location},
            "interaction": {"system_prompt": sysprompt, "prompt": prompt, "response": new_response, "full_response": original_response},
        }

        # Write to file with minimal whitespace but still readable
        with open(self.log_path, "a") as f:
            json.dump(interaction, f, indent=2, separators=(",", ": "))
            # input()
            f.write("\n")
            f.flush()
        with open(self.compact_log_path, "a") as f:
            json.dump(interaction, f, separators=(",", ": "))
            f.write("\n")
            f.flush()

        print(".", end="", flush=True)

        if os.getenv("STREAMLIT") == "True":
            if "game_updates" not in st.session_state:
                st.session_state.game_updates = []
            
            # Format the message without newlines to prevent HTML display issues
            message = f"Game {self.game_index} - Step {step}, {self.player.name} done."
            st.session_state.game_updates.append(message)
        
            # Force a render of the updates container without a full rerun
            if "update_placeholder" in st.session_state and st.session_state.update_placeholder is not None:
                # Increment the counter to create a unique key
                if "update_counter" not in st.session_state:
                    st.session_state.update_counter = 0
                st.session_state.update_counter += 1
                unique_key = f"live_updates_display_{st.session_state.update_counter}"
                
                # Update the display with current game updates
                with st.session_state.update_placeholder.container():
                    st.subheader("Game Updates")
                    updates_text = "\n".join([f"{msg}" for msg in st.session_state.game_updates])
                    st.text_area("Game Updates", value=updates_text, height=150, key=unique_key, label_visibility="collapsed")
    
    async def send_request(self, messages):
        """Send a POST request to OpenRouter API with the provided messages."""
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "top_p": 1,
            "frequency_penalty": 0,
            "presence_penalty": 0,
            "repetition_penalty": 1,
            "top_k": 0,
        }
        
        async with aiohttp.ClientSession() as session:
            for attempt in range(10):
                try:
                    async with session.post(self.api_url, headers=headers, data=json.dumps(payload)) as response:
                        if response is None:
                            print("API request failed: response is None.")
                            continue
                        if response.status == 200:
                            data = await response.json()
                            if "choices" not in data:
                                print("API request failed: 'choices' key not in response.")
                                continue
                            if not data["choices"]:
                                print("API request failed: 'choices' key is empty in response.")
                                continue
                            return data["choices"][0]["message"]["content"]
                except Exception as e:
                    print(f"API request failed. Retrying... ({attempt + 1}/5)")
                    continue
            return 'SPEAK: ...'

    def respond(self, message):
        all_info = self.player.all_info_prompt()
        prompt = f"{all_info}\n{message}"
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": prompt},
        ]
        return self.send_request(messages)

    async def choose_action(self, timestep):
        available_actions = self.player.get_available_actions()
        all_info = self.player.all_info_prompt()
        # phase = "Meeting phase" if len(available_actions) == 1 else "Task phase"
        phase = "Meeting phase" if len(available_actions) == 1 or all(a.name == "VOTE" for a in available_actions) else "Task phase"

        messages = [
            {"role": "system", "content": self.system_prompt},
            {
                "role": "user",
                "content": f"Summarization: {self.summarization}\n\n{all_info}\n\nMemory: {self.processed_memory}\
                    \n\nPhase: {phase}. Return your output.",
            },
        ]
        
        # log everything needed to reproduce the interaction
        full_prompt = {
            "Summarization": self.summarization,
            "All Info": all_info,
            "Memory": self.processed_memory,
            "Phase": phase,
        }
        
        response = await self.send_request(messages)

        self.log_interaction(sysprompt=self.system_prompt, prompt=full_prompt, original_response=response, step=timestep)

        pattern = r"^\[Condensed Memory\]((.|\n)*)\[Thinking Process\]((.|\n)*)\[Action\]((.|\n)*)$"
        match = re.search(pattern, response)
        if match:
            memory = match.group(1).strip()
            summarization = match.group(3).strip()
            output_action = match.group(5).strip()
            self.summarization = summarization
            self.processed_memory = memory
        else:
            output_action = response.strip()

        for action in available_actions:
            if repr(action) in output_action:
                return action
            elif "SPEAK: " in repr(action) and "SPEAK: " in output_action:
                message = output_action.split("SPEAK: ")[1]
                action.message = message
                return action
            else:
                action.message = '...'
        return action

    def choose_observation_location(self, map):
        return random.sample(map, 1)[0]


class RandomAgent(Agent):
    def __init__(self, player):
        super().__init__(player)

    def choose_action(self):
        available_actions = self.player.get_available_actions()
        action = np.random.choice(available_actions)
        if action.name == "speak":
            message = "Hello, I am a crewmate."
            action.provide_message(message)
        return action

    def choose_observation_location(self, map):
        return random.sample(map, 1)[0]


class HumanAgent(Agent):
    def __init__(self, player, tools=None, game_index=0, agent_config=None, list_of_impostors=None):
        super().__init__(player)
        self.model = "homosapiens/brain-1.0"
        self.tools = tools
        self.game_index = game_index
        self.summarization = "No thought process has been made."
        self.processed_memory = "No memory has been processed."
        self.log_path = os.getenv("EXPERIMENT_PATH") + "/agent-logs.json"
        self.compact_log_path = os.getenv("EXPERIMENT_PATH") + "/agent-logs-compact.json"
        
        # Initialize global session state if it doesn't exist
        if os.getenv("STREAMLIT") == "True":
            # Global session state for actions across page refreshes
            if "human_actions" not in st.session_state:
                st.session_state.human_actions = {}
            if "action_history" not in st.session_state:
                st.session_state.action_history = {}
    
    async def choose_action(self, timestep):
        all_info = self.player.all_info_prompt()
        available_actions = self.player.get_available_actions()
        
        # Log the start of action selection
        action_prompt = f"Available actions:\n" + "\n".join([f"{i+1}: {action}" for i, action in enumerate(available_actions)])
        full_prompt = {
            "All Info": all_info,
            "Available Actions": action_prompt
        }
        
        if os.getenv("STREAMLIT") == "True":
            # Use a unique key for this player and timestep
            action_key = f"action_{self.player.name}_{timestep}"
            history_key = f"history_{self.player.name}"
            
            # Check if we already have an action for this timestep in the session state
            if action_key in st.session_state.human_actions:
                # Retrieve the stored action
                action_data = st.session_state.human_actions[action_key]
                selected_action = action_data["action"]
                message = action_data.get("message", "")
                
                # Apply the message if this is a SPEAK action
                if selected_action.name == "SPEAK" and message:
                    selected_action.provide_message(message)
                
                # Log the action
                self.log_interaction(
                    sysprompt="Human Agent", 
                    prompt=full_prompt,
                    original_response=f"[Action] {selected_action}" + (f" with message: {message}" if selected_action.name == "SPEAK" and message else ""), 
                    step=timestep
                )
                
                # Save to action history
                if history_key not in st.session_state.action_history:
                    st.session_state.action_history[history_key] = []
                st.session_state.action_history[history_key].append({
                    "timestep": timestep,
                    "action": str(selected_action),
                    "message": message if selected_action.name == "SPEAK" and message else ""
                })
                
                # Clean up this action so it doesn't get reused
                del st.session_state.human_actions[action_key]
                
                return selected_action
            
            # Setup sidebar with persistent player information
            with st.sidebar:
                st.header(f"Game {self.game_index}")
                st.subheader(f"Step {timestep}")
                st.write(f"Player: {self.player.name}")
                st.write(f"Role: {self.player.identity}")
                st.write(f"Location: {self.player.location}")
                
                # Show action history in sidebar
                if history_key in st.session_state.action_history and st.session_state.action_history[history_key]:
                    st.subheader("Your Previous Actions")
                    for entry in st.session_state.action_history[history_key]:
                        action_str = f"Step {entry['timestep']}: {entry['action']}"
                        if entry.get('message'):
                            action_str += f" - '{entry['message']}'"
                        st.write(action_str)
            
            # Display game information
            st.header("Game Information")
            st.text_area("Current Game State", value=all_info, height=300, key=f"game_info_{self.player.name}_{timestep}")
            
            # Create a form for action selection to avoid immediate reruns
            with st.form(key=f"action_form_{self.player.name}_{timestep}"):
                st.header("Choose an Action")
                # Action selection via radio buttons
                action_options = list(range(len(available_actions)))
                selected_idx = st.radio(
                    "Select an action:", 
                    options=action_options,
                    format_func=lambda i: f"{i+1}: {available_actions[i]}",
                    key=f"action_radio_{self.player.name}_{timestep}"
                )
                
                # Message input for SPEAK action
                message = ""
                if available_actions[selected_idx].name == "SPEAK":
                    message = st.text_area(
                        "Enter your message:",
                        key=f"message_{self.player.name}_{timestep}"
                    )
                
                # Submit button
                submitted = st.form_submit_button("Submit Action")
                if submitted:
                    # Get the selected action
                    selected_action = available_actions[selected_idx]
                    
                    # Store in session state for persistence across refreshes
                    st.session_state.human_actions[action_key] = {
                        "action": selected_action,
                        "message": message
                    }
                    
                    # If it's a SPEAK action, add the message
                    if selected_action.name == "SPEAK" and message:
                        selected_action.provide_message(message)
                    
                    # Log the interaction
                    self.log_interaction(
                        sysprompt="Human Agent", 
                        prompt=full_prompt,
                        original_response=f"[Action] {selected_action}" + (f" with message: {message}" if selected_action.name == "SPEAK" and message else ""), 
                        step=timestep
                    )
                    
                    # Save to action history for display
                    if history_key not in st.session_state.action_history:
                        st.session_state.action_history[history_key] = []
                    st.session_state.action_history[history_key].append({
                        "timestep": timestep,
                        "action": str(selected_action),
                        "message": message if selected_action.name == "SPEAK" and message else ""
                    })
                    
                    return selected_action
            
            # If we're here, we need to wait for the action to be selected
            # We'll do this with a polling loop
            while action_key not in st.session_state.human_actions:
                await asyncio.sleep(0.1)
            
            # Once the action is submitted (in another Streamlit run), we'll get here
            action_data = st.session_state.human_actions[action_key]
            selected_action = action_data["action"]
            message = action_data.get("message", "")
            
            # Apply the message if this is a SPEAK action
            if selected_action.name == "SPEAK" and message:
                selected_action.provide_message(message)
            
            # Clean up this action so it doesn't get reused
            del st.session_state.human_actions[action_key]
            
            return selected_action
        else:
            # Command line interface
            print(f"{str(self.player)}")
            print(all_info)
            print("Choose an action:")
            for i, action in enumerate(available_actions):
                print(f"{i+1}: {action}")
                
            stop_triggered = False
            valid_input = False
            while (not stop_triggered) and (not valid_input):
                try:
                    action_idx = int(input())
                    if action_idx == 0:
                        stop_triggered = True
                    elif action_idx < 1 or action_idx > len(available_actions):
                        raise ValueError(f"Invalid input. Please enter a number between 1 and {len(available_actions)}.")
                    else:
                        valid_input = True
                except:
                    print("Invalid input. Please enter a number.")
                    continue
                    
            if stop_triggered:
                raise ValueError("Game stopped by user.")
                
            selected_action = available_actions[action_idx - 1]
            
            if selected_action.name == "SPEAK":
                print("Enter your response:")
                action_message = input()
                selected_action.provide_message(action_message)
                self.log_interaction(sysprompt="Human Agent", prompt=full_prompt, 
                                     original_response=f"[Action] {selected_action} with message: {action_message}", 
                                     step=timestep)
            else:
                self.log_interaction(sysprompt="Human Agent", prompt=full_prompt, 
                                     original_response=f"[Action] {selected_action}", 
                                     step=timestep)
        
            return selected_action

    def respond(self, message):
        if os.getenv("STREAMLIT") == "True":
            player_key = f"player_{self.player.name}"
            player_state = st.session_state[player_key]
            
            # If response already submitted, return it
            if player_state["response_submitted"]:
                response = player_state["response_text"]
                # Reset state for next interaction
                player_state["response_submitted"] = False
                player_state["response_text"] = ""
                return response
            
            # Show message
            st.header("Respond to Message")
            st.write(message)
            
            # Response input
            response_key = f"response_{self.player.name}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            player_state["response_text"] = st.text_area("Your response:", key=response_key)
            
            # Submit button
            if st.button("Submit Response", key=f"submit_response_{self.player.name}_{datetime.now().strftime('%Y%m%d%H%M%S')}"):
                player_state["response_submitted"] = True
                st.success("Response submitted!")
            
            # Wait for response
            time.sleep(0.1)
            return self.respond(message)
        else:
            print(message)
            response = input()
            return response

    def choose_observation_location(self, map):
        map_list = list(map)
        
        if os.getenv("STREAMLIT") == "True":
            player_key = f"player_{self.player.name}"
            player_state = st.session_state[player_key]
            
            # If observation already submitted, return it
            if player_state["observation_submitted"]:
                room_choice = player_state["observation_choice"]
                # Reset state for next interaction
                player_state["observation_submitted"] = False
                player_state["observation_choice"] = None
                return room_choice
            
            st.header("Choose Observation Location")
            st.write("Please select the room you wish to observe:")
            
            # Room selection
            room_key = f"room_choice_{self.player.name}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            player_state["observation_choice"] = st.radio("Select a room:", map_list, key=room_key)
            
            # Submit button
            if st.button("Confirm Observation", key=f"confirm_obs_{self.player.name}_{datetime.now().strftime('%Y%m%d%H%M%S')}"):
                player_state["observation_submitted"] = True
                st.success(f"Observation location confirmed: {player_state['observation_choice']}")
            
            # Wait for observation
            time.sleep(0.1)
            return self.choose_observation_location(map)
        else:
            print("Please select the room you wish to observe:")
            for i, room in enumerate(map_list):
                print(f"{i}: {room}")
            while True:
                try:
                    index = int(input())
                    if index < 0 or index >= len(map_list):
                        print(f"Invalid input. Please enter a number between 0 and {len(map_list) - 1}.")
                    else:
                        return map_list[index]
                except:
                    print("Invalid input. Please enter a number.")

    def log_interaction(self, sysprompt, prompt, original_response, step):
        """Log human player interactions similar to LLMAgent"""
        interaction = {
            'game_index': 'Game ' + str(self.game_index),
            'step': step,
            "timestamp": str(datetime.now()),
            "player": {"name": self.player.name, "identity": self.player.identity, "personality": self.player.personality, "model": self.model, "location": self.player.location},
            "interaction": {"system_prompt": sysprompt, "prompt": prompt, "response": original_response, "full_response": original_response},
        }

        # Write to file
        with open(self.log_path, "a") as f:
            json.dump(interaction, f, indent=2, separators=(",", ": "))
            f.write("\n")
            f.flush()
        with open(self.compact_log_path, "a") as f:
            json.dump(interaction, f, separators=(",", ": "))
            f.write("\n")
            f.flush()

        print(".", end="", flush=True)

        if os.getenv("STREAMLIT") == "True":
            if "game_updates" not in st.session_state:
                st.session_state.game_updates = []
            
            message = f"Game {self.game_index} - Step {step}, {self.player.name} done."
            st.session_state.game_updates.append(message)
        
            if "update_placeholder" in st.session_state and st.session_state.update_placeholder is not None:
                if "update_counter" not in st.session_state:
                    st.session_state.update_counter = 0
                st.session_state.update_counter += 1
                unique_key = f"live_updates_display_{st.session_state.update_counter}"
                
                with st.session_state.update_placeholder.container():
                    st.subheader("Game Updates")
                    updates_text = "\n".join([f"{msg}" for msg in st.session_state.game_updates])
                    st.text_area("Game Updates", value=updates_text, height=150, key=unique_key, label_visibility="collapsed")


class LLMHumanAgent(HumanAgent, LLMAgent):
    def __init__(self, player, tools=None, game_index=0, agent_config=None, list_of_impostors=None):
        super().__init__(player, tools, game_index, agent_config, list_of_impostors)

    async def choose_action(self, timestep):
        return await HumanAgent.choose_action(self, timestep)

    def respond(self, message):
        return HumanAgent.respond(self, message)
        
    def log_interaction(self, sysprompt, prompt, original_response, step):
        return HumanAgent.log_interaction(self, sysprompt, prompt, original_response, step)