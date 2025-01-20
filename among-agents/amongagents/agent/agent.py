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
        self.log_path = os.path.join(self.script_dir, "agent-logs/agent-logs.json")

    # def log_interaction(self, prompt, response, type):
    #     """
    #     Helper method to store model interactions in properly nested JSON format.
    #     Handles deep nesting and properly parses all string-formatted dictionaries.
        
    #     Args:
    #         prompt (str): The input prompt containing dictionary-like strings
    #         response (str): The model response containing bracketed sections
    #         type (str): The type of interaction
    #     """
    #     def parse_dict_string(s):
    #         if isinstance(s, str):
    #             try:
    #                 # Replace any single quotes with double quotes for valid JSON
    #                 s = s.replace("'", '"')
    #                 # Try parsing as JSON first
    #                 try:
    #                     return json.loads(s)
    #                 except json.JSONDecodeError:
    #                     # If parsing fails, try ast.literal_eval
    #                     return ast.literal_eval(s)
    #             except:
    #                 # If parsing fails, keep original string
    #                 return s
    #         return s

    #     def parse_game_info(info_string):
    #         """Parse the all_info string into a structured nested JSON."""
    #         result = {}
    #         sections = info_string.strip().split('\n')
    #         current_section = None
            
    #         for line in sections:
    #             line = line.strip()
    #             if not line:
    #                 continue
                    
    #             # Game Time
    #             if line.startswith('Game Time:'):
    #                 parts = line.split(': ')[1].split('/')
    #                 result['game_time'] = {
    #                     'current': int(parts[0]),
    #                     'total': int(parts[1])
    #                 }
    #             # Phase
    #             elif line.startswith('Current phase:'):
    #                 result['phase'] = line.split(': ')[1]
    #             elif line.startswith('In this phase,'):
    #                 result['phase_description'] = line
    #             # Location
    #             elif line.startswith('Current Location:'):
    #                 result['current_location'] = line.split(': ')[1]
    #             # Players
    #             elif line.startswith('Players in'):
    #                 location = line.split('Players in ')[1].split(':')[0]
    #                 players = line.split(': ')[1].split(', ')
    #                 result['players'] = {
    #                     'location': location,
    #                     'list': players
    #                 }
    #             # Section headers
    #             elif line == 'Observation history:':
    #                 current_section = 'observations'
    #                 result['observations'] = []
    #             elif line == 'Action history:':
    #                 current_section = 'actions'
    #                 result['actions'] = []
    #             elif line == 'Your Assigned Tasks:':
    #                 current_section = 'tasks'
    #                 result['tasks'] = []
    #             elif line == 'Available actions:':
    #                 current_section = 'available_actions'
    #                 result['available_actions'] = []
    #             # Content under sections
    #             elif current_section == 'observations':
    #                 if not line.startswith('No observations'):
    #                     result['observations'].append(line)
    #             elif current_section == 'actions':
    #                 if not line.startswith('No actions'):
    #                     result['actions'].append(line)
    #             elif current_section == 'tasks' and line.startswith(('1.', '2.', '3.')):
    #                 parts = line.split(': ', 1)
    #                 if len(parts) == 2:
    #                     task_num = parts[0].split('.')[0]
    #                     task_type = parts[0].split('. ')[1]
    #                     task_info = parts[1].split(' (')
    #                     task = {
    #                         'number': int(task_num),
    #                         'type': task_type,
    #                         'name': task_info[0],
    #                         'location': task_info[1].rstrip(')')
    #                     }
    #                     result['tasks'].append(task)
    #             elif current_section == 'tasks' and line.startswith('Path:'):
    #                 if result['tasks']:  # Add path to the last task
    #                     result['tasks'][-1]['path'] = line.replace('Path: ', '')
    #             elif current_section == 'available_actions' and line.startswith(('1.', '2.', '3.', '4.', '5.', '6.', '7.')):
    #                 parts = line.split('. ', 1)
    #                 action = {
    #                     'number': int(parts[0]),
    #                     'action': parts[1]
    #                 }
    #                 result['available_actions'].append(action)

    #         # Clean up empty lists
    #         if not result.get('observations', []):
    #             result['observations'] = "No observations"
    #         if not result.get('actions', []):
    #             result['actions'] = "No actions"
                
    #         return result

    #     # Parse the prompt
    #     if isinstance(prompt, str):
    #         try:
    #             prompt = parse_dict_string(prompt)
    #             # Also parse nested dictionary strings in the prompt
    #             if isinstance(prompt, dict):
    #                 for key, value in prompt.items():
    #                     if key == "all_info":
    #                         # Use the new parser for all_info
    #                         prompt[key] = parse_game_info(value)
    #                     else:
    #                         prompt[key] = parse_dict_string(value)
    #         except:
    #             # If parsing fails, keep original string
    #             pass

    #     # Parse the response into structured sections
    #     if isinstance(response, str):
    #         sections = {}
    #         current_section = None
    #         current_content = []
            
    #         for line in response.split('\n'):
    #             line = line.strip()
    #             if line.startswith('[') and line.endswith(']'):
    #                 if current_section:
    #                     sections[current_section] = ' '.join(current_content).strip()
    #                     current_content = []
    #                 current_section = line[1:-1]  # Remove brackets
    #             elif line and current_section:
    #                 current_content.append(line)
                    
    #         if current_section and current_content:
    #             sections[current_section] = ' '.join(current_content).strip()
                
    #         response = sections if sections else response

    #         # Try to parse any dictionary strings in the response sections
    #         if isinstance(response, dict):
    #             for key, value in response.items():
    #                 response[key] = parse_dict_string(value)

    #     # Create the interaction object with proper nesting
    #     interaction = {
    #         'timestamp': str(datetime.now()),
    #         'player': {
    #             'name': self.player.name,
    #             'identity': self.player.identity
    #         },
    #         'interaction': {
    #             'type': type,
    #             'prompt': prompt,
    #             'response': response
    #         }
    #     }

    #     # Write to file with minimal whitespace but still readable
    #     with open(self.log_path, 'a') as f:
    #         json.dump(interaction, f, indent=2, separators=(',', ': '))
    #         f.write('\n')  # Add newline between entries

    #     print('Interaction logged.')

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
                try:
                    # Replace any single quotes with double quotes for valid JSON
                    s = s.replace("'", '"')
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

        def parse_game_info(info_string):
            """Parse the all_info string into a structured nested JSON."""
            result = {}
            sections = info_string.strip().split('\n')
            current_section = None
            
            for line in sections:
                line = line.strip()
                if not line:
                    continue
                    
                # Game Time and Phase
                if line.startswith('Game Time:'):
                    parts = line.split(': ')[1].split('/')
                    result['game_time'] = {
                        'current': int(parts[0]),
                        'total': int(parts[1])
                    }
                elif line.startswith('Current phase:'):
                    # Handle phase with discussion round
                    phase_parts = line.split(' - ')
                    result['phase'] = {
                        'main': phase_parts[0].split(': ')[1],
                        'sub_phase': phase_parts[1] if len(phase_parts) > 1 else None
                    }
                elif line.startswith('In this phase,'):
                    result['phase_description'] = []
                    result['phase_description'].append(line)
                elif not line.startswith(('Current Location:', 'Players in', 'Observation history:', 'Action history:', 'Your Assigned Tasks:', 'Available actions:')) and current_section is None:
                    # Additional phase description lines
                    result['phase_description'].append(line)
                # Location and Players
                elif line.startswith('Current Location:'):
                    result['current_location'] = line.split(': ')[1]
                elif line.startswith('Players in'):
                    location = line.split('Players in ')[1].split(':')[0]
                    players = line.split(': ')[1].split(', ')
                    result['players'] = {
                        'location': location,
                        'list': players
                    }
                # Section headers
                elif line == 'Observation history:':
                    current_section = 'observations'
                    result['observations'] = []
                elif line == 'Action history:':
                    current_section = 'actions'
                    result['actions'] = []
                elif line == 'Your Assigned Tasks:':
                    current_section = 'tasks'
                    result['tasks'] = []
                elif line == 'Available actions:':
                    current_section = 'available_actions'
                    result['available_actions'] = []
                # Content under sections
                elif current_section == 'observations':
                    if line.startswith(('1.', '2.', '3.', '4.', '5.')):
                        parts = line.split(': ', 1)
                        if len(parts) > 1:
                            observation = {
                                'number': int(parts[0].rstrip('.').split('.')[0]),
                                'content': parts[1]
                            }
                            # Parse timestep and type if present
                            content_parts = parts[1].split(' ')
                            if content_parts[0].startswith('Timestep'):
                                observation['timestep'] = int(content_parts[1].rstrip(':'))
                                type_start = parts[1].find('[') + 1
                                type_end = parts[1].find(']')
                                if type_start > 0 and type_end > 0:
                                    observation['type'] = parts[1][type_start:type_end]
                                    observation['action'] = parts[1][type_end + 2:]
                            result['observations'].append(observation)
                        elif not line.startswith('No observations'):
                            result['observations'].append(line)
                elif current_section == 'actions':
                    if not line.startswith('No actions'):
                        result['actions'].append(line)
                elif current_section == 'tasks' and line.startswith(('1.', '2.', '3.')):
                    parts = line.split(': ', 1)
                    if len(parts) == 2:
                        task_num = parts[0].split('.')[0]
                        task_type = parts[0].split('. ')[1]
                        task_info = parts[1].split(' (')
                        task = {
                            'number': int(task_num),
                            'type': task_type,
                            'name': task_info[0],
                            'location': task_info[1].rstrip(')')
                        }
                        result['tasks'].append(task)
                elif current_section == 'tasks' and line.startswith('Path:'):
                    if result['tasks']:  # Add path to the last task
                        result['tasks'][-1]['path'] = line.replace('Path: ', '')
                elif current_section == 'available_actions' and line.startswith(('1.', '2.', '3.', '4.', '5.', '6.', '7.')):
                    parts = line.split('. ', 1)
                    action = {
                        'number': int(parts[0]),
                        'action': parts[1]
                    }
                    result['available_actions'].append(action)

            # Clean up empty lists and join phase description
            if not result.get('observations', []):
                result['observations'] = "No observations"
            if not result.get('actions', []):
                result['actions'] = "No actions"
            if 'phase_description' in result:
                result['phase_description'] = ' '.join(result['phase_description'])
                
            return result

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
            
        # Ensure prompt is properly nested
        if isinstance(prompt, dict):
            for key, value in prompt.items():
                if key == "all_info":
                    prompt[key] = parse_game_info(value)
                else:
                    prompt[key] = parse_dict_string(value)

        # Parse the response into structured sections
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
            json.dump(interaction, f, indent=2, separators=(',', ': '))
            f.write('\n')  # Add newline between entries

        print('Interaction logged.')

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
            prompt=str(full_prompt),
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