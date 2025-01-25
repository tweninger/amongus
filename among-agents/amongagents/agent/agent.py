import ast
import json
import os
import random
import re
from datetime import datetime
from typing import Any

import numpy as np
import requests
# from amongagents.agent.prompts import *
from amongagents.agent.simpler_prompts import *


class Agent:
    def __init__(self, player):
        self.player = player

    def respond(self, message):
        return "..."

    def choose_action(self):
        return None


class LLMAgent(Agent):
    def __init__(self, player, tools, game_index):
        super().__init__(player)
        if player.identity == "Crewmate":
            system_prompt = CREWMATE_PROMPT.format(name=player.name)
            if player.personality is not None:
                system_prompt += PERSONALITY_PROMPT.format(
                    personality=CrewmatePersonalities[player.personality]
                )
            system_prompt += CREWMATE_EXAMPLE
        elif player.identity == "Impostor":
            system_prompt = IMPOSTOR_PROMPT.format(name=player.name)
            if player.personality is not None:
                system_prompt += PERSONALITY_PROMPT.format(
                    personality=ImpostorPersonalities[player.personality]
                )
            system_prompt += IMPOSTOR_EXAMPLE

        self.system_prompt = system_prompt
        self.model = "microsoft/phi-4"
        self.temperature = 0.7
        self.api_key = os.getenv("OPENROUTER_API_KEY")
        self.api_url = "https://openrouter.ai/api/v1/chat/completions"
        self.summarization = "no thought process has been made"
        self.processed_memory = "no memory has been processed"
        self.chat_history = []
        self.tools = tools
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.log_path = os.getenv("EXPERIMENT_PATH") + "/agent-logs.json"
        self.game_index = game_index

    def log_interaction(self, prompt, response, step):
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
        if isinstance(response, str):
            sections = {}
            current_section = None
            current_content = []

            for line in response.split("\n"):
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

            response = sections if sections else response

            # Parse any dictionary strings in the response sections and handle [Action]
            if isinstance(response, dict):
                for key, value in response.items():
                    if isinstance(value, str):
                        response[key] = extract_action(value)
                    else:
                        response[key] = parse_dict_string(value)

        # Create the interaction object with proper nesting
        interaction = {
            'game_index': 'Game ' + str(self.game_index),
            'step': step,
            "timestamp": str(datetime.now()),
            "player": {"name": self.player.name, "identity": self.player.identity},
            "interaction": {"prompt": prompt, "response": response},
        }

        # Write to file with minimal whitespace but still readable
        with open(self.log_path, "a") as f:
            json.dump(interaction, f, separators=(",", ": "))
            f.write("\n")
            f.flush()

        print(".", end="", flush=True)

    def send_request(self, messages):
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

        response = requests.post(
            self.api_url, headers=headers, data=json.dumps(payload)
        )
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
        else:
            raise Exception(
                f"API request failed: {response.status_code} {response.text}"
            )

    def respond(self, message):
        all_info = self.player.all_info_prompt()
        prompt = f"{all_info}\n{message}"
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": prompt},
        ]
        return self.send_request(messages)

    def choose_action(self, timestep):
        available_actions = self.player.get_available_actions()
        all_info = self.player.all_info_prompt()
        phase = "Meeting phase" if len(available_actions) == 1 else "Task phase"

        full_prompt = {
            "summarization": self.summarization,
            "all_info": all_info,
            "memory": self.processed_memory,
        }

        messages = [
            {"role": "system", "content": self.system_prompt},
            {
                "role": "user",
                "content": f"{full_prompt}\n\n{all_info}\n\nPhase: {phase}. What should I do?",
            },
        ]
        response = self.send_request(messages)

        self.log_interaction(prompt=full_prompt, response=response, step=timestep)

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
    def __init__(self, player):
        super().__init__(player)

    def choose_action(self):
        print(f"{str(self.player)}")

        available_actions = self.player.get_available_actions()
        print(self.player.all_info_prompt())
        stop_triggered = False
        valid_input = False
        while (not stop_triggered) and (not valid_input):
            print("Choose an action:")
            try:
                action_idx = int(input())
                if action_idx == 0:
                    stop_triggered = True
                elif action_idx < 1 or action_idx > len(available_actions):
                    raise ValueError(
                        f"Invalid input. Please enter a number between 1 and {len(available_actions)}."
                    )
                else:
                    valid_input = True

            except:
                print("Invalid input. Please enter a number.")
                continue
        if stop_triggered:
            raise ValueError("Game stopped by user.")
        action = available_actions[action_idx - 1]
        if action.name == "SPEAK":
            message = self.speak()
            action.provide_message(message)
        if action.name == "SPEAK":
            action.provide_message(message)
        return action

    def respond(self, message):
        print(message)
        response = input()
        return response

    def speak(self):
        print("Enter your response:")
        message = input()
        return message

    def choose_observation_location(self, map):
        map = list(map)
        print("Please select the room you wish to observe:")
        for i, room in enumerate(map):
            print(f"{i}: " + room)
        while True:
            index = int(input())
            if index < 0 or index >= len(map):
                print(
                    f"Invalid input. Please enter a number between 0 and {len(map) - 1}."
                )
            else:
                print(map)
                print("index", index)
                print("map[index]", map[index])
                return map[index]


class LLMHumanAgent(HumanAgent, LLMAgent):
    def __init__(self, player):
        super(LLMHumanAgent, self).__init__(player)

    def choose_action(self):
        return HumanAgent.choose_action(self)

    def respond(self, message):
        return LLMAgent.respond(self, message)
