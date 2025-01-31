import os
import sys
import json
import plotly.express as px
import plotly.graph_objects as go
import numpy as np
import requests
import pandas as pd
import asyncio
import aiohttp
import httpx
import aiofiles
import re
import argparse
from pprint import pprint as pp
import aiofiles

from evals_prompts import system_prompt_base, strategy_prompt

from pandas import DataFrame, json_normalize
from typing import List, Dict, Any, Tuple, Union, Optional

LOGS_PATH: str = "../expt-logs/"
RESULTS_PATH: str = "./results/"

import dotenv
dotenv.load_dotenv()

sys.path.append("..")

from utils import load_agent_logs_df

def setup_experiment(expt_name, results_path) -> None:
    agent_logs_path: str = os.path.join(LOGS_PATH, expt_name + "/agent-logs-compact.json")
    agent_df: DataFrame = load_agent_logs_df(agent_logs_path)
    # keep the columns needed for the analysis
    cols_to_keep: List[str] = [
        'game_index', 'step', 'player.name', 'player.identity', 'interaction.prompt.all_info',
        'interaction.response.Condensed Memory', 'action', 'thought']
    agent_df = agent_df[cols_to_keep]
    # fill all NaNs with an empty string
    agent_df = agent_df.fillna("")
    results_file: str = os.path.join(results_path, expt_name + "_strategy_skill.json")
    # clear the results file
    with open(results_file, "w") as f:
        f.write("")
    return agent_df, results_file

async def send_request(messages, model):
    for attempt in range(10):
        try:
            async with aiohttp.ClientSession() as client:
                async with client.post(
                    url="https://openrouter.ai/api/v1/chat/completions",
                    headers = {"Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}"},
                    data=json.dumps({
                        "model": model,
                        "messages": messages,
                    })
                    ) as response:
                    await asyncio.sleep(0.02) # sleep for 1ms before returning
                    data = await response.json()
                    return data['choices'][0]['message']['content']
        except Exception as e:
            print(f"Error: {e}")
            print(f"Attempt {attempt + 1} failed. Retrying...")
            await asyncio.sleep(0.05) # sleep for 50ms before retrying

async def process_row(index, row, results_file, behavior, model):
    identity = row['player.identity']
    memory = row['interaction.response.Condensed Memory']
    game_info = row['interaction.prompt.all_info']
    action = row['action']
    thought = row['thought']
    name = row['player.name']

    if behavior == "strategy_score":
        behavior_prompt = strategy_prompt
    system_prompt, full_prompt = system_prompt_base(name, identity, memory, action, thought, game_info), behavior_prompt

    messages = [{"role": "system", "content": system_prompt},{"role": "user", "content": full_prompt},]
    try:
        response = await send_request(messages, model)
        # import pdb; pdb.set_trace()
        pattern = r"\[Strategy Score\]:\s*(\d+)\s*\[Explanation\]:\s*(.+)"
        match = re.search(pattern, response, re.DOTALL)
        if not match:
            print("Invalid response format")
            print(response)
            input()
        strategy_score = int(match.group(1))
        explanation = match.group(2)
    except Exception as e:
        print(f"Error: {e}")
        strategy_score = -1
        explanation = ""

    result_dict = {
        "game_index": row['game_index'],
        "step": row['step'],
        "player_name": row['player.name'],
        "strategy_score": strategy_score,
        "action": action,
        "player_identity": identity,
        "game_info": game_info,
        "memory": memory,
        "thought": thought,
        "explanation": explanation
    }
    async with aiofiles.open(results_file, "a") as f:
        await f.write(json.dumps(result_dict, separators=(",", ": ")) + "\n")
        print(f"." , end="")

    return index, strategy_score, explanation

async def main(agent_df, results_file, model, run_async=True):
    if run_async:
        tasks = [process_row(index, row, results_file, behavior, model) for index, row in agent_df.iterrows()]
        await asyncio.gather(*tasks)
    else:
        for index, row in agent_df.iterrows():
            await process_row(index, row, results_file, behavior, model)

parser = argparse.ArgumentParser(description="Run an AmongUs evaluation.")
parser.add_argument("--expt_name", type=str, default="2025-01-30_prompting_v2", help="Experiment name.")
parser.add_argument("--behavior", type=str, default="strategy_score", help="Behavior to evaluate.")
parser.add_argument("--evaluator", type=str, default="meta-llama/llama-3.3-70b-instruct", help="Evaluator LLM to use.")
args = parser.parse_args()
expt_name = args.expt_name
behavior = args.behavior
model = args.evaluator

agent_df, results_file = setup_experiment(expt_name, RESULTS_PATH)

# import pdb; pdb.set_trace()

asyncio.run(main(agent_df, results_file, model, run_async=True))