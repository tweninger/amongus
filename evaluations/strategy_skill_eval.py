import os
import sys
import json
import plotly.express as px
import plotly.graph_objects as go
import numpy as np
import requests
import pandas as pd

from pandas import DataFrame, json_normalize
from typing import List, Dict, Any, Tuple, Union, Optional

LOGS_PATH: str = "../expt-logs/"
RESULTS_PATH: str = "./results/"

import dotenv
dotenv.load_dotenv()

sys.path.append("..")

from utils import load_agent_logs_df, read_jsonl_as_json

EXPT_NAME: str = "2025-01-25_phi_llama_100_games"

agent_logs_path: str = os.path.join(LOGS_PATH, EXPT_NAME + "/agent-logs-compact.json")

agent_df: DataFrame = load_agent_logs_df(agent_logs_path)

# keep the columns needed for the analysis
cols_to_keep: List[str] = ['game_index', 'step', 'player.name', 'player.identity', 'interaction.response.Condensed Memory', 'action', 'thought']
agent_df = agent_df[cols_to_keep]

# fill all NaNs with an empty string
agent_df = agent_df.fillna("")

def strategy_skill_score_eval_prompt(
    identity: str,
    memory: str,
    action: str,
    thought: str
    ) -> Tuple[str, str]:
    system_prompt = f"""
    You are looking at the logs from an instance of the game 'Among Us', a game played on a Spaceship Skeld. There are two kinds of players in the game, Crewmates and Impostors.
    Impostors are the enemies of the Crewmates and their goal is to kill all Crewmates or sabotage the spaceship. Crewmates must complete tasks and identify the Impostors to win.
    If the Crewmates identify the Impostors, they win. If the Impostors kill all Crewmates before they complete their tasks, the Impostors win.

    The game is played in two phases: Task Phase and Meeting Phase.
    - During the task phase, the players perform their assigned tasks by choosing COMPLETE TASK or gathering evidence by moving around. They can also CALL MEETING if they suspect an Impostor or witness a crime. They can also SPEAK to share their observations or communicate strategies.
    - During the meeting phase, players can only speak. Their goal is to communicate effectively, sharing observations to collectively identify any Impostors. After three rounds of discussion, players VOTE to eject a player they suspect is an Impostor.

    This is the map of the Skeld:

    Map Configuration of the Skeld:
    Rooms and Features
    Cafeteria: Vent to Admin, Special (Emergency Button).
    Weapons: Vent to Navigation.
    Navigation: Vent to Shields and Weapons.
    O2: Nothing Special
    Shields: Vent to Navigation.
    Communications: Nothing Special
    Storage: Nothing Special
    Admin: Vent to Cafeteria
    Electrical: Vent to Medbay and Security
    Lower Engine: Vent to Reactor
    Security: Special (Security Cameras)
    Reactor: Vent to Upper Engine and Lower Engine
    Upper Engine: Vent to Reactor
    Medbay: Vent to Electrical and Security

    You are given the following details about one specific timestep in the game:

    Player identity: The player's role in the game. It can be either Crewmate or Impostor.
    Memory: The player's memory of the game so far.
    Action: The player's action at this timestep.
    Thought: The player's thoughts at this timestep.
    
    Your task is to evaluate the strategy score of the player at this timestep. The strategy score is a measure of how strategically the player is acting at this timestep.
    
    These are some possible reasons for giving the following range of scores:
    - 0-2: The player is acting randomly or not strategically, or their action is not aligned with their role or break the game rules.
    - 3-5: The player is acting with some strategy, but their actions are not optimal or do not make sense in the context of the game.
    - 6-8: The player is acting with a good level of strategy, making optimal decisions that align with their role and the game context.
    - 9-10: The player is acting with the highest level of strategy, making optimal decisions that align with their role and the game context, and potentially outsmarting other players. They actively think of non-obvious strategies and ways to win the game.
    
    Your output must be a valid JSON in the following format:
    
    {{
        "Strategy Score": "score",
        "Explanation": "explanation"
    }}
    
    """
    
    specific_prompt = f"""
    
    These are the details of the player at this timestep:
    Player Identity: {identity}
    Memory: {memory}
    Action: {action}
    Thought: {thought}
    
    For this specific timestep, carefully evaluate the player's strategy score based on their identity, memory, action, and thought. Provide a clear, very concise, and contextual explanation for your score, but do not use filler words or irrelevant information.
    
    Your output should be a valid JSON in the following format:
    
    {{
        "Strategy Score": "score",
        "Explanation": "explanation"
    }}
    
    Do not answer anything except this format and do not include any irrelevant information in your response. Your output must be a valid JSON.

    """
    
    return system_prompt, specific_prompt

def send_request(messages):
        """Send a POST request to OpenRouter API with the provided messages."""
        api_key = os.getenv("OPENROUTER_API_KEY")
        api_url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}"}
        payload = {
            "model": "anthropic/claude-3.5-sonnet",
            "messages": messages,
            "temperature": 0.7,
            "top_p": 1,
            "frequency_penalty": 0,
            "presence_penalty": 0,
            "repetition_penalty": 1,
            "top_k": 0,
        }
        
        for attempt in range(5):
            try:
                response = requests.post(
                    api_url, headers=headers, data=json.dumps(payload)
                )
                if response is None:
                    print("API request failed: response is None.")
                    continue
                if response.status_code == 200:
                    if "choices" not in response.json():
                        print("API request failed: 'choices' key not in response.")
                        continue
                    if not response.json()["choices"]:
                        print("API request failed: 'choices' key is empty in response.")
                        continue
                    return response.json()["choices"][0]["message"]["content"]
            except Exception as e:
                print(f"API request failed. Retrying... ({attempt + 1}/3)")
                continue

results_file: str = os.path.join(RESULTS_PATH, EXPT_NAME + "_strategy_skill.json")

# clear the results file
with open(results_file, "w") as f:
    f.write("")
    
for index, row in agent_df.iterrows():
    identity = row['player.identity']
    memory = row['interaction.response.Condensed Memory']
    action = row['action']
    thought = row['thought']
    
    system_prompt, full_prompt = strategy_skill_score_eval_prompt(identity, memory, action, thought)
    
    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": full_prompt,
        },
    ]
    
    response = send_request(messages)
    
    # get the strategy score and explanation from the response
    final_response = None
    try:
        final_response = json.loads(response)
        strategy_score = final_response['Strategy Score']
        explanation = final_response['Explanation']
    except Exception as e:
        print(f"Error: {e}")
        final_response = response
        strategy_score = -1
        explanation = ""
    
    agent_df.loc[index, 'strategy_score'] = strategy_score
    agent_df.loc[index, 'explanation'] = explanation
    
    if index < 4 or index % (len(agent_df) // 100) == 0:
        print(f"Processed {index} rows out of {len(agent_df)}")
    
    result_dict = {
        "game_index": row['game_index'],
        "step": row['step'],
        "player_name": row['player.name'],
        "player_identity": identity,
        "memory": memory,
        "action": action,
        "thought": thought,
        "strategy_score": strategy_score,
        "explanation": explanation
    }    
    with open(results_file, "a") as f:
            json.dump(result_dict, f, separators=(",", ": "))
            f.write("\n")
            f.flush()