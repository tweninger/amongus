import ast
import asyncio
import json
import os
import random
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

import aiohttp
import numpy as np
from amongagents.agent.neutral_prompts import *

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_EXPERIMENT_PATH = REPO_ROOT / "human_trials" / "logs"
SUPPORTED_LLM_PROVIDERS = {"openai", "gemini", "anthropic"}


def _experiment_path() -> str:
    experiment_path = Path(os.environ.get("EXPERIMENT_PATH", DEFAULT_EXPERIMENT_PATH)).expanduser()
    experiment_path.mkdir(parents=True, exist_ok=True)
    return str(experiment_path)


def _normalize_provider(provider: str | None, model: str) -> str:
    if provider:
        provider = provider.strip().lower()
    elif "/" in model:
        provider = model.split("/", 1)[0].strip().lower()
        if provider == "google":
            provider = "gemini"
    else:
        provider = "gemini"

    if provider not in SUPPORTED_LLM_PROVIDERS:
        raise ValueError(
            f"Unsupported LLM_PROVIDER={provider!r}. "
            f"Use one of: {', '.join(sorted(SUPPORTED_LLM_PROVIDERS))}."
        )
    return provider


def _normalize_model_name(provider: str, model: str) -> str:
    model = model.strip()
    provider_prefixes = {
        "openai": ("openai/",),
        "gemini": ("google/", "gemini/"),
        "anthropic": ("anthropic/",),
    }
    for prefix in provider_prefixes[provider]:
        if model.startswith(prefix):
            return model.removeprefix(prefix)
    return model


def _provider_api_key(provider: str) -> str | None:
    env_name = {
        "openai": "OPENAI_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
    }[provider]
    if provider == "gemini":
        return os.getenv(env_name) or os.getenv("GOOGLE_API_KEY")
    return os.getenv(env_name)


def _anthropic_messages(messages: list[dict]) -> tuple[str, list[dict]]:
    system_parts = []
    conversation = []
    for message in messages:
        role = message.get("role", "user")
        content = message.get("content", "")
        if role == "system":
            system_parts.append(content)
        else:
            conversation.append({
                "role": "assistant" if role == "assistant" else "user",
                "content": content,
            })
    return "\n\n".join(system_parts), conversation


def _gemini_contents(messages: list[dict]) -> tuple[dict | None, list[dict]]:
    system_parts = []
    contents = []
    for message in messages:
        role = message.get("role", "user")
        content = message.get("content", "")
        if role == "system":
            system_parts.append(content)
        else:
            contents.append({
                "role": "model" if role == "assistant" else "user",
                "parts": [{"text": content}],
            })
    system_instruction = None
    if system_parts:
        system_instruction = {"parts": [{"text": "\n\n".join(system_parts)}]}
    return system_instruction, contents


# Write one LLM request/response to the analysis database. The web server creates
# the full schema; this local CREATE keeps standalone engine runs usable too.
def _log_interaction_to_db(entry: dict):
    db_path = os.path.join(_experiment_path(), "game_data.db")
    player = entry.get("player", {})
    interaction = entry.get("interaction", {})
    try:
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS llm_interactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                timestep INTEGER,
                player_name TEXT NOT NULL,
                player_role TEXT NOT NULL,
                player_personality TEXT,
                player_model TEXT NOT NULL,
                player_location TEXT,
                system_prompt TEXT,
                prompt TEXT NOT NULL,
                response TEXT NOT NULL,
                full_response TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO llm_interactions (
                game_id, occurred_at, timestep, player_name, player_role,
                player_personality, player_model, player_location, system_prompt,
                prompt, response, full_response
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry.get("game_index"), entry.get("timestamp"), entry.get("step"),
                player.get("name"), player.get("identity"), player.get("personality"),
                player.get("model"), player.get("location"), interaction.get("system_prompt"),
                json.dumps(interaction.get("prompt")), json.dumps(interaction.get("response")),
                interaction.get("full_response") or "",
            ),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"error inserting interaction to db: {e}")

# Set Flask environment variable to True by default
if "FLASK" not in os.environ:
    os.environ["FLASK"] = "True"

# Global dictionary to store futures for human actions, keyed by game_id
human_action_futures: Dict[int, asyncio.Future] = {}

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
            system_prompt += f"List of impostors: {list_of_impostors}"##### MAKE CONFIGURABLE #####
            model = random.choice(agent_config["IMPOSTOR_LLM_CHOICES"])

        self.system_prompt = system_prompt
        self.model = model
        self.temperature = 0.7
        self.provider = _normalize_provider(os.getenv("LLM_PROVIDER"), self.model)
        self.provider_model = _normalize_model_name(self.provider, self.model)
        self.api_key = _provider_api_key(self.provider)
        self.summarization = "No thought process has been made."
        self.processed_memory = "No memory has been processed."
        self.chat_history = []
        self.tools = tools
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        experiment_path = _experiment_path()
        self.log_path = os.path.join(experiment_path, "agent-logs.json")
        self.compact_log_path = os.path.join(experiment_path, "agent-logs-compact.json")
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
                except (ValueError, SyntaxError, TypeError, json.JSONDecodeError):
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

        new_response = None

        # Parse the prompt
        if isinstance(prompt, str):
            try:
                prompt = parse_dict_string(prompt)
            except (ValueError, SyntaxError, TypeError, json.JSONDecodeError):
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
            'game_index': str(self.game_index),
            'step': step,
            "timestamp": str(datetime.now()),
            "player": {"name": self.player.name, "identity": self.player.identity, "personality": self.player.personality, "model": self.model, "location": self.player.location},
            "interaction": {"system_prompt": sysprompt, "prompt": prompt, "response": new_response, "full_response": original_response},
        }

        # Write to file with minimal whitespace but still readable
        with open(self.log_path, "a") as f:
            json.dump(interaction, f, indent=2, separators=(",", ": "))
            f.write("\n")
            f.flush()
        with open(self.compact_log_path, "a") as f:
            json.dump(interaction, f, separators=(",", ": "))
            f.write("\n")
            f.flush()
        _log_interaction_to_db(interaction)

        print(".", end="", flush=True)

    def _build_llm_request(self, messages):
        if not self.api_key:
            raise RuntimeError(f"Missing API key for LLM_PROVIDER={self.provider}.")

        if self.provider == "openai":
            return (
                "https://api.openai.com/v1/chat/completions",
                {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                {
                    "model": self.provider_model,
                    "messages": messages,
                    "temperature": self.temperature,
                },
            )

        if self.provider == "anthropic":
            system_prompt, anthropic_messages = _anthropic_messages(messages)
            payload = {
                "model": self.provider_model,
                "messages": anthropic_messages,
                "max_tokens": int(os.getenv("LLM_MAX_TOKENS", "1024")),
                "temperature": self.temperature,
            }
            if system_prompt:
                payload["system"] = system_prompt
            return (
                "https://api.anthropic.com/v1/messages",
                {
                    "x-api-key": self.api_key,
                    "anthropic-version": os.getenv("ANTHROPIC_VERSION", "2023-06-01"),
                    "Content-Type": "application/json",
                },
                payload,
            )

        system_instruction, gemini_contents = _gemini_contents(messages)
        payload = {
            "contents": gemini_contents,
            "generationConfig": {
                "temperature": self.temperature,
                "maxOutputTokens": int(os.getenv("LLM_MAX_TOKENS", "1024")),
            },
        }
        if system_instruction:
            payload["systemInstruction"] = system_instruction
        return (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.provider_model}:generateContent?key={self.api_key}",
            {"Content-Type": "application/json"},
            payload,
        )

    def _extract_llm_text(self, data):
        if self.provider == "openai":
            return data["choices"][0]["message"]["content"]

        if self.provider == "anthropic":
            parts = data.get("content", [])
            return "".join(part.get("text", "") for part in parts if part.get("type") == "text")

        parts = data["candidates"][0]["content"].get("parts", [])
        return "".join(part.get("text", "") for part in parts)

    async def send_request(self, messages):
        """Send a chat-style request to the configured direct LLM provider."""
        try:
            url, headers, payload = self._build_llm_request(messages)
        except Exception as exc:
            print(f"LLM configuration failure for {self.model}: {exc}")
            return {"content": "SPEAK: The AI connection failed after 10 attempts."}

        async with aiohttp.ClientSession() as session:
            for attempt in range(10):
                try:
                    async with session.post(url, headers=headers, json=payload) as response:
                        if response.status == 200:
                            data = await response.json()
                            text = self._extract_llm_text(data)
                            if text:
                                return text
                            print(f"LLM API returned no text for {self.provider}/{self.provider_model}.")
                        else:
                            error_details = await response.text()
                            print(
                                f"LLM API failure ({response.status}) for "
                                f"{self.provider}/{self.provider_model}: {error_details}"
                            )
                except Exception as exc:
                    print(
                        f"LLM API request failed. Retrying... ({attempt + 1}/10) "
                        f"for {self.provider}/{self.provider_model}: {exc}"
                    )
                    continue

        return {"content": "SPEAK: The AI connection failed after 10 attempts."}

    def respond(self, message):
        all_info = self.player.all_info_prompt()
        prompt = f"{all_info}\n{message}"
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": prompt},
        ]
        return self.send_request(messages)
    

    def parse_flexible_sections(self, text):
        sections = {"condensed memory": "", "thinking process": "", "action": ""}
        current_section = None
        buffer = []

        def flush_buffer():
            nonlocal current_section, buffer
            if current_section:
                sections[current_section] = "\n".join(buffer).strip()
                buffer = []

        # Flexible section header pattern
        header_pattern = re.compile(
            r'^\s*\[?\s*(condensed memory|thinking process|action)\s*\]?\s*(.*)$',
            re.IGNORECASE
        )

        lines = text.strip().splitlines()

        for line in lines:
            match = header_pattern.match(line)
            if match:
                flush_buffer()
                current_section = match.group(1).lower()
                inline_content = match.group(2).strip()
                buffer = [inline_content] if inline_content else []
            else:
                if current_section:
                    buffer.append(line)

        flush_buffer()
        #print("SECTIONS: ", sections)
        return sections


    async def choose_action(self, timestep):
        available_actions = self.player.get_available_actions()
        all_info = self.player.all_info_prompt()
        if all(action.name == "VOTE" for action in available_actions) and available_actions:
            phase = "Meeting phase - Voting Round. You MUST cast a VOTE. Do NOT SPEAK."
        elif any(action.name == "SPEAK" for action in available_actions):
            phase = "Meeting phase - Discussion Round. You MUST SPEAK. Do NOT VOTE yet. Keep your spoken message to 1-3 sentences, conversational and direct."
        else:
            phase = "Task phase"

        # Iterate through each available action object and converts to bullet newline menu for LLM
        actions_str = "\n".join(f"- {repr(action)}" for action in available_actions)

        messages = [
            {"role": "system", "content": self.system_prompt},
            {
                "role": "user",
                "content": (
                    f"Summarization: {self.summarization}\n\n{all_info}\n\n"
                    f"Memory: {self.processed_memory}\n\n"
                    f"Phase: {phase}.\n"
                    f"Available actions (choose EXACTLY one, copy the format exactly):\n{actions_str}\n\n"
                    f"Return your output."
                ),
            },
        ]

        # log everything needed to reproduce the interaction
        full_prompt = {
            "Summarization": self.summarization,
            "All Info": all_info,
            "Memory": self.processed_memory,
            "Phase": phase,
            "Available Actions": actions_str,
        }
        
        response = await self.send_request(messages)

        self.log_interaction(sysprompt=self.system_prompt, prompt=full_prompt, original_response=response, step=timestep)

        # Standardize response to a str
        if isinstance(response, dict):
            raw_message_text = response.get('content', str(response))
        else:
            raw_message_text = str(response)

        ai_role = getattr(self.player, 'identity', 'Unknown')
        if not isinstance(ai_role, str):
            ai_role = getattr(self, 'identity', 'Unknown')

        print("\n" + "="*50)
        print(f"AI THOUGHTS - {self.player.name} ({ai_role})")
        print(raw_message_text)
        print("="*50 + "\n")
        parsed_message = self.parse_flexible_sections(raw_message_text)

        # Update agent state
        # Use get with fallbacks to avoid key errors
        self.processed_memory = parsed_message.get('condensed memory', 'No memory.')
        self.summarization = parsed_message.get('thinking process', 'No thought.')
        output_action = parsed_message.get('action', 'SPEAK: ...')

        # pattern = r"^\[Condensed Memory\]((.|\n)*)\[Thinking Process\]((.|\n)*)\[Action\]((.|\n)*)$"
        # searchMessage = response['message']
        # match = re.search(pattern, searchMessage['content'])
        # if match:
        #     memory = match.group(1).strip()
        #     summarization = match.group(3).strip()
        #     output_action = match.group(5).strip()
        #     self.summarization = summarization
        #     self.processed_memory = memory
        # else:
        #     pattern = r"^Condensed Memory((.|\n)*)Thinking Process((.|\n)*)Action((.|\n)*)$"
        #     match = re.search(pattern, searchMessage['content'])
        #     if match:
        #         memory = match.group(1).strip()
        #         summarization = match.group(3).strip()
        #         output_action = match.group(5).strip()
        #         self.summarization = summarization
        #         self.processed_memory = memory
        #     else:
        #         pattern = r"""
        #             \[?\s*Condensed\s+Memory\s*\]?    # Match 'Condensed Memory' with optional brackets and spaces
        #             (.*?)                             # Capture everything up to...
        #             \[?\s*Thinking\s+Process\s*\]?    # Match 'Thinking Process' with optional brackets and spaces
        #             (.*?)                             # Capture everything up to...
        #             \[?\s*Action\s*\]?                # Match 'Action' with optional brackets and spaces
        #             (.*)                              # Capture everything after 'Action'
        #             """
                
        #         match = re.search(pattern, searchMessage['content'])
        #     if match:
        #         #memory = match.group(1).strip()
        #         #summarization = match.group(3).strip()
        #         output_action = match.group(5).strip()
        #         self.summarization = summarization
        #         self.processed_memory = memory
        #     else:
        #         pattern = r"^Action((.|\n)*)$"
        #         match = re.search(pattern, searchMessage['content'])
        #         if match:
        #             #memory = match.group(1).strip()
        #             #summarization = match.group(3).strip()
        #             output_action = match.group(5).strip()
        #             self.summarization = summarization
        #             self.processed_memory = memory
        #         else:
        #             pattern = r"^SPEAK|KILL|VENT|MOVE((.|\n)*)$"
        #             match = re.search(pattern, searchMessage['content'])
        #             if match:
        #                 #memory = match.group(1).strip()
        #                 #summarization = match.group(3).strip()
        #                 output_action = match.group(5).strip()
        #                 self.summarization = summarization
        #                 self.processed_memory = memory
        #             else:
        #                 print("HELP", searchMessage['content'])
        #                 output_action = response.strip()
        #                 print("WAIT? ", output_action)

        for action in available_actions:
            if action.name == "VOTE":
                # Strip identity suffix so crewmates can match e.g. "Player 5: green"
                # even when repr is "VOTE Player 5: green (Impostor)"
                target = re.sub(r'\s*\([^)]*\)\s*$', '', str(action.other_player.name)).strip()
                if target and target in output_action:
                    return action
            elif repr(action) in output_action:
                return action
            elif "SPEAK: " in repr(action) and "SPEAK: " in output_action:
                message = output_action.split("SPEAK: ")[1]
                await asyncio.sleep(0.10 * len(message))
                action.message = message
                return action
            else:
                action.message = '...'
        return action

    def choose_observation_location(self, map):
        if isinstance(map, (list, tuple)):
            return random.choice(map)
        else:
            # For sets, dicts, or other non-sequence types
            return random.choice(list(map))


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
        experiment_path = _experiment_path()
        self.log_path = os.path.join(experiment_path, "agent-logs.json")
        self.compact_log_path = os.path.join(experiment_path, "agent-logs-compact.json")
        self.current_available_actions = []
        self.current_step = 0
        self.max_steps = 50  # Default value, will be updated from game config
        self.action_future = None  # Store the future as an instance variable
        self.condensed_memory = ""  # Store the condensed memory (scratchpad) between turns
    
    def update_max_steps(self, max_steps):
        """Update the max_steps value from the game config."""
        self.max_steps = max_steps

    async def choose_action(self, timestep: int):
        """
        Chooses an action, either via web interface (if FLASK_ENABLED=True)
        or command line (if FLASK_ENABLED=False).
        """
        use_flask = os.getenv("FLASK_ENABLED", "True") == "True"
        all_info = self.player.all_info_prompt()
        self.current_available_actions = self.player.get_available_actions()
        self.current_step = timestep

        if use_flask:
            # --- Web Interface Logic ---            
            action_prompt = "Waiting for human action via web interface.\nAvailable actions:\n" + "\n".join([f"{i+1}: {str(action)}" for i, action in enumerate(self.current_available_actions)])
            full_prompt = {
                "All Info": all_info,
                "Available Actions": action_prompt,
                "Current Step": f"{timestep}/{self.max_steps}",
                "Current Player": self.player.name
            }

            loop = asyncio.get_event_loop()
            self.action_future = loop.create_future()  # Store in instance variable
            
            # Use game_id from the server instead of game_index
            # The game_id is passed to the HumanAgent when it's created
            game_id = getattr(self, 'game_id', self.game_index)
            human_action_futures[game_id] = self.action_future
            
            print(f"[Agent] Created future for game {game_id}")
            print(f"[Agent] Available futures: {list(human_action_futures.keys())}")

            print(f"\n[Game {game_id}] Human player {self.player.name}'s turn. Waiting for action via web interface...")
            print(f"Available actions: {[str(a) for a in self.current_available_actions]}")

            try:
                chosen_action_data = await self.action_future
                action_idx = chosen_action_data.get("action_index")
                action_message = chosen_action_data.get("message")
                condensed_memory = chosen_action_data.get("condensed_memory", "")
                thinking_process = chosen_action_data.get("thinking_process", "")

                # Update the condensed memory if provided
                if condensed_memory:
                    self.condensed_memory = condensed_memory

                if action_idx is None or action_idx < 0 or action_idx >= len(self.current_available_actions):
                    print(f"[Game {game_id}] Invalid action index received: {action_idx}. Defaulting to first action.")
                    selected_action = self.current_available_actions[0]
                else:
                    selected_action = self.current_available_actions[action_idx]

                # Format the response log to match LLMAgent format
                response_log = ""
                if self.condensed_memory:
                    response_log += f"[Condensed Memory]\n{self.condensed_memory}\n\n"
                if thinking_process:
                    response_log += f"[Thinking Process]\n{thinking_process}\n\n"
                
                response_log += f"[Action] {str(selected_action)}"
                
                # Check if action requires a message (e.g., SPEAK)
                # Use str() and check for attributes robustly
                is_speak_action = False
                if hasattr(selected_action, 'name'): # Check attribute exists
                    is_speak_action = selected_action.name == "SPEAK"
                elif "SPEAK" in str(selected_action): # Fallback to string check
                    is_speak_action = True
                
                if is_speak_action and action_message:
                    if hasattr(selected_action, 'provide_message'):
                        selected_action.provide_message(action_message)
                    elif hasattr(selected_action, 'message'): # Fallback to setting attribute
                        selected_action.message = action_message
                    response_log += f" {action_message}"

                # Update the prompt to not include "Waiting for human action via web interface"
                full_prompt = {
                    "All Info": all_info,
                    "Available Actions": "\n".join([f"{i+1}: {str(action)}" for i, action in enumerate(self.current_available_actions)]),
                    "Current Step": f"{timestep}/{self.max_steps}",
                    "Current Player": self.player.name
                }

                self.log_interaction(sysprompt="Human Agent (Web)", prompt=full_prompt,
                                     original_response=response_log,
                                     step=timestep)
                
                # Clear the future and actions only after successful action selection
                if game_id in human_action_futures:
                    print(f"[Agent] Deleting future for game {game_id} after successful action")
                    del human_action_futures[game_id]
                self.current_available_actions = []
                self.action_future = None
                
                return selected_action

            except asyncio.CancelledError:
                print(f"[Game {game_id}] Human action cancelled.")
                # Clean up on cancellation
                if game_id in human_action_futures:
                    print(f"[Agent] Deleting future for game {game_id} after cancellation")
                    del human_action_futures[game_id]
                self.current_available_actions = []
                self.action_future = None
                raise
        else:
            # --- Command Line Interface Logic ---            
            action_prompt = "Available actions:\n" + "\n".join([f"{i+1}: {str(action)}" for i, action in enumerate(self.current_available_actions)])
            full_prompt = {
                "All Info": all_info,
                "Available Actions": action_prompt
            }
            
            print(f"\n--- [Game {self.game_index}] Player: {self.player.name} ({self.player.identity if self.player.identity else 'Role Unknown'}) ---")
            print(all_info)
            print("\nChoose an action:")
            for i, action in enumerate(self.current_available_actions):
                print(f"{i+1}: {str(action)}")
            print("(Enter 0 to stop game)")
                
            stop_triggered = False
            valid_input = False
            selected_action = None
            action_idx_chosen = -1

            while (not stop_triggered) and (not valid_input):
                try:
                    user_input = input("> ")
                    action_idx_chosen = int(user_input)
                    if action_idx_chosen == 0:
                        stop_triggered = True
                    elif action_idx_chosen < 1 or action_idx_chosen > len(self.current_available_actions):
                        print(f"Invalid input. Please enter a number between 1 and {len(self.current_available_actions)} (or 0 to stop).")
                    else:
                        valid_input = True
                except ValueError:
                    print("Invalid input. Please enter a number.")
                    continue
                    
            if stop_triggered:
                print("Stopping game as requested by user.")
                # How to signal stop? Raise exception? Return specific value?
                # For now, raise an exception that the game loop might catch.
                raise KeyboardInterrupt("Game stopped by user via CLI.")
                
            selected_action = self.current_available_actions[action_idx_chosen - 1]
            response_log = f"[Action] {str(selected_action)}"
            
            # Check if action requires a message using string check
            is_speak_action = False
            if hasattr(selected_action, 'name'):
                 is_speak_action = selected_action.name == "SPEAK"
            elif "SPEAK" in str(selected_action):
                 is_speak_action = True

            if is_speak_action:
                print("Enter your message:")
                action_message = input("> ")
                if hasattr(selected_action, 'provide_message'):
                     selected_action.provide_message(action_message)
                elif hasattr(selected_action, 'message'):
                     selected_action.message = action_message
                else:
                     print("Warning: Could not set message for SPEAK action.")
                response_log += f" {action_message}"
            
            self.log_interaction(sysprompt="Human Agent (CLI)", prompt=full_prompt, 
                                 original_response=response_log, 
                                 step=timestep)
        
            self.current_available_actions = [] # Clear actions after use
            return selected_action # Return synchronously within async def

    def get_current_state_for_web(self) -> Dict[str, Any]:
        """
        Returns the necessary state for the web UI when it's the human's turn.
        Uses string checks for action properties.
        """
        available_actions_web = []
        for action in self.current_available_actions:
            action_str = str(action)
            requires_message = False
            if hasattr(action, 'name'):
                 requires_message = action.name == "SPEAK"
            elif "SPEAK" in action_str:
                 requires_message = True
                 
            available_actions_web.append({
                "name": action_str,
                "requires_message": requires_message
            })
            
        return {
            "is_human_turn": True,
            "player_name": self.player.name,
            "player_info": self.player.all_info_prompt(),
            "available_actions": available_actions_web,
            "current_step": f"{self.current_step}/{self.max_steps}",
            "current_player": self.player.name,
            "condensed_memory": self.condensed_memory  # Include the condensed memory in the state
        }

    def respond(self, message):
        print(message)
        response = input()
        return response

    def choose_observation_location(self, map):
        map_list = list(map)
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
            except (ValueError, IndexError, TypeError):
                print("Invalid input. Please enter a number.")

    def log_interaction(self, sysprompt, prompt, original_response, step):
        """
        Helper method to store model interactions in properly nested JSON format.
        Handles deep nesting and properly parses all string-formatted dictionaries.
        Correctly separates Memory, Thinking, and Action sections.
        """
        sections = {}

        # Clean the original response slightly for easier parsing
        response_text = original_response.strip()

        # Use regex to find sections robustly, ignoring case for tags
        action_match = re.search(r"\[Action\](.*)", response_text, re.DOTALL | re.IGNORECASE)
        memory_match = re.search(r"\[Condensed Memory\](.*?)(\[(Thinking Process|Action)\]|$)", response_text, re.DOTALL | re.IGNORECASE)
        thinking_match = re.search(r"\[Thinking Process\](.*?)(\[(Condensed Memory|Action)\]|$)", response_text, re.DOTALL | re.IGNORECASE)

        # Initialize keys to ensure they exist, defaulting to empty string
        sections["Condensed Memory"] = ""
        sections["Thinking Process"] = ""

        # Extract content based on matches, overwriting defaults if found
        if memory_match:
            sections["Condensed Memory"] = memory_match.group(1).strip()

        if thinking_match:
            sections["Thinking Process"] = thinking_match.group(1).strip()

        if action_match:
            action_text = action_match.group(1).strip()
            # Remove leading number format like "1. "
            action_text_cleaned = re.sub(r"^\d+\.\s*", "", action_text).strip()

            # Assign the full cleaned action string directly, regardless of message presence
            if action_text_cleaned:
                sections["Action"] = action_text_cleaned
            # If action_text_cleaned is empty after stripping number, don't add Action section

        # Handle cases where tags might be missing or text exists outside tags
        # (This logic might need refinement depending on expected variations)
        # For now, prioritize explicitly tagged sections.

        # Create the interaction object with proper nesting
        interaction = {
            'game_index': f"{os.environ.get('SESSION_ID', 'unknown')}_Game {self.game_index}",
            'step': step,
            "timestamp": str(datetime.now()),
            "player": {"name": self.player.name, "identity": self.player.identity, "personality": self.player.personality, "model": self.model, "location": self.player.location},
            "interaction": {"system_prompt": sysprompt, "prompt": prompt, "response": sections, "full_response": original_response},
        }

        # Ensure log directories exist
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        os.makedirs(os.path.dirname(self.compact_log_path), exist_ok=True)

        # Write to file with minimal whitespace but still readable
        try:
            with open(self.log_path, "a") as f:
                json.dump(interaction, f, indent=2, separators=(",", ": "))
                f.write("\n")
                f.flush()
            with open(self.compact_log_path, "a") as f:
                json.dump(interaction, f, separators=(",", ":"))
                f.write("\n")
                f.flush()
        except Exception as e:
            print(f"Error writing to log file: {e}") # Add error logging
        _log_interaction_to_db(interaction)

        print(".", end="", flush=True)

class LLMHumanAgent(HumanAgent, LLMAgent):
    def __init__(self, player, tools=None, game_index=0, agent_config=None, list_of_impostors=None):
        super().__init__(player, tools, game_index, agent_config, list_of_impostors)

    async def choose_action(self, timestep):
        return await HumanAgent.choose_action(self, timestep)

    def respond(self, message):
        return HumanAgent.respond(self, message)
        
    def log_interaction(self, sysprompt, prompt, original_response, step):
        return HumanAgent.log_interaction(self, sysprompt, prompt, original_response, step)
