from typing import Any
from amongagents.envs.tools import AgentResponseOutputParser
import numpy as np
import random
import os

from langchain_openai import ChatOpenAI

from langchain.agents import create_openai_functions_agent
from langchain.agents import AgentExecutor

from datetime import datetime
import json

from langchain_core.prompts import ChatPromptTemplate, PromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate, MessagesPlaceholder
import re
from .prompts import *
import ast

class Agent():
    def __init__(self, player):
        self.player = player
    
    def respond(self, message):
        return "..."
    
    def choose_action(self):
        return None

class LLMAgent(Agent):
    def __init__(self, player, tools):
        super().__init__(player)
        if player.identity == 'Crewmate':
            system_prompt = CREWMATE_PROMPT.format(name=player.name)
            if player.personality is not None:
                system_prompt += PERSONALITY_PROMPT.format(personality=CrewmatePersonalities[player.personality])
            system_prompt += CREWMATE_EXAMPLE
        elif player.identity == 'Impostor':
            system_prompt = IMPOSTOR_PROMPT.format(name=player.name)
            if player.personality is not None:
                system_prompt += PERSONALITY_PROMPT.format(personality=ImpostorPersonalities[player.personality])
            system_prompt += IMPOSTOR_EXAMPLE
            
        chat_template = ChatPromptTemplate.from_messages(
            [
                ("system", system_prompt),
                HumanMessagePromptTemplate(prompt=PromptTemplate(input_variables=["all_info", "summarization", "memory"], template=LLM_ACTION_TEMPLATE)),
                MessagesPlaceholder(variable_name="agent_scratchpad"),
            ]
        )
            
        # llm = ChatOpenAI(model="gpt-3.5-turbo", temperature=0.7, openai_api_key=os.getenv("OPENAI_API_KEY"))
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.7, openai_api_key=os.getenv("OPENAI_API_KEY"))
        self.tools = tools
            
        self.openai_agent = create_openai_functions_agent(llm, tools, chat_template)
        self.executor = AgentExecutor(agent=self.openai_agent, tools=tools, verbose=False)
        self.executor.name = player.name 
        self.summarization = 'no thought process has been made'
        self.processed_memory = 'no memory has been processed'

        self.chat_history = [] # LOG
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.log_path = os.getenv("EXPERIMENT_PATH") + "agent-logs.json" if os.getenv("EXPERIMENT_PATH") else os.path.join(self.script_dir, "agent-logs/agent-logs.json")


    def log_interaction(self, prompt, response, type):
        """
        Helper method to store model interactions in properly nested JSON format.
        Handles deep nesting and properly parses all string-formatted dictionaries.
        
        Args:
            prompt (str): The input prompt containing dictionary-like strings
            response (str): The model response containing bracketed sections
            type (str): The type of interaction
        """
        def parse_dict_string(s):
            if isinstance(s, str):
                # Replace any single quotes with double quotes for valid JSON
                s = s.replace("'", '"')
                s = s.replace('\"', '"')
                # Properly escape newlines for JSON
                s = s.replace('\\n', '\\\\n')
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
            if '[Action]' in text:
                action_parts = text.split('[Action]')
                thought = action_parts[0].strip()
                action = action_parts[1].strip()
                return {
                    'thought': thought,
                    'action': action
                }
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
            
            for line in response.split('\n'):
                line = line.strip()
                if line.startswith('[') and line.endswith(']'):
                    if current_section:
                        sections[current_section] = ' '.join(current_content).strip()
                        current_content = []
                    current_section = line[1:-1]  # Remove brackets
                elif line and current_section:
                    current_content.append(line)
                    
            if current_section and current_content:
                sections[current_section] = ' '.join(current_content).strip()
                
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
            'timestamp': str(datetime.now()),
            'player': {
                'name': self.player.name,
                'identity': self.player.identity
            },
            'interaction': {
                'type': type,
                'prompt': prompt,
                'response': response
            }
        }

        # Write to file with minimal whitespace but still readable
        with open(self.log_path, 'a') as f:
            # If the file is empty, write the first entry without a comma
            if f.tell() == 0:
                f.write('[\n')
            else:
                f.write(',\n')    
            json.dump(interaction, f, indent=2, separators=(',', ': '))
            f.flush()

        print('.', end='', flush=True)

    def respond(self, message):
        all_info = self.player.all_info_prompt()
        prompt = f"{all_info}\n{message}"
        results = self.executor.invoke({"all_info": prompt})

        # LOG
        self.log_interaction(
            prompt=prompt,
            response=results['output'],
            type="RESPONSE"
        )

        return results['output']
        
    def choose_action(self):
        available_actions = self.player.get_available_actions()
        all_info = self.player.all_info_prompt()
        phase = 'Meeting phase' if len(available_actions) == 1 else 'Task phase'

        full_prompt = {
            "summarization": self.summarization,
            "all_info": all_info,
            "memory": self.processed_memory,
        }
        
        results = self.executor.invoke(full_prompt)

        # LOG
        self.log_interaction(
            prompt=full_prompt,
            response=results['output'],
            type="ACTION"
        )
        
        pattern = r"^\[Condensed Memory\]((.|\n)*)\[Thinking Process\]((.|\n)*)\[Action\]((.|\n)*)$"
        match = re.search(pattern, results['output'])
        if match:
            # print(results['output'].split('|||'))
            memory = match.group(1)
            summarization = match.group(3)
            output_action = match.group(5)
            output_action = output_action.strip()
            summarization = summarization.strip()
            memory = memory.strip()
            self.summarization = summarization
            self.processed_memory = memory
        else:
            output_action = results['output']
        
        for action in available_actions:
            if repr(action) in output_action:
                return action
            elif 'SPEAK: ' in repr(action) and 'SPEAK: ' in output_action:                
                message = output_action.split('SPEAK: ')[1]
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
                    raise ValueError(f"Invalid input. Please enter a number between 1 and {len(available_actions)}.")
                else:
                    valid_input = True
                   
            except:
                print("Invalid input. Please enter a number.")
                continue
        if stop_triggered:
            raise ValueError("Game stopped by user.")
        action = available_actions[action_idx-1]
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
                print(f"Invalid input. Please enter a number between 0 and {len(map) - 1}.")
            else:
                print(map)
                print('index', index)
                print('map[index]', map[index])
                return map[index]

class LLMHumanAgent(HumanAgent, LLMAgent):
    def __init__(self, player):
        super(LLMHumanAgent, self).__init__(player)
    
    def choose_action(self):
        return HumanAgent.choose_action(self)
    
    def respond(self, message):
        return LLMAgent.respond(self, message)