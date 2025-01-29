import json
from pandas import DataFrame, json_normalize
from functools import reduce
from typing import List, Dict
import pandas as pd

def load_game_summary(filepath: str) -> pd.DataFrame:
    # Read each line of the JSONL file
    with open(filepath, 'r') as file:
        data = [json.loads(line.strip()) for line in file]
    
    # Extract Game, Winner, and Winner Reason
    games_summary = [
        {
            "Game": game_id,
            "Winner": game_details.get("winner"),
            "Winner Reason": game_details.get("winner_reason")
        }
        for entry in data
        for game_id, game_details in entry.items()
    ]
    
    # Create DataFrame
    return pd.DataFrame(games_summary)

def read_jsonl_as_json(file_path):
    with open(file_path, 'r') as file:
        return [json.loads(line) for line in file]

def load_agent_logs_df(path: str) -> DataFrame:

    df: DataFrame = json_normalize(read_jsonl_as_json(path))
    
    action_cols = [
        "interaction.response.Action",
        "interaction.response.Action.action",
        "interaction.response.SPEAK Strategy.action",
        "interaction.response.ACTION",
        "interaction.response.Thinking Process.action",
    ]
    
    thinking_cols = [
        "interaction.response.Thinking Process",
        "interaction.response.Thinking Process.thought",
        "interaction.response.SPEAK Strategy.thought",
        "interaction.response.SPEAK Strategy",
        "interaction.response",
        "interaction.response.Action.thought",
    ]
    

    df["action"] = reduce(
        lambda x, y: x.combine_first(df[y]) if y in df else x,
        action_cols,
        df.assign(action=None)["action"]  # Start with a column of None
    )
    
    df["thought"] = reduce(
        lambda x, y: x.combine_first(df[y]) if y in df else x,
        thinking_cols,
        df.assign(thought=None)["thought"]  # Start with a column of None
    )
    
    df = df.drop(columns=(action_cols + thinking_cols), errors='ignore')

    return df