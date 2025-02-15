import os
import sys
import json
import plotly.express as px
import plotly.graph_objects as go
import numpy as np
import requests
import pandas as pd
import torch as t
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader, random_split
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split
from pprint import pprint as pp
from transformers import AutoTokenizer, AutoModelForCausalLM
from pandas import DataFrame, json_normalize
from typing import List, Dict, Any, Tuple, Union, Optional
import dotenv

LOGS_PATH: str = "../evaluations/results/"
RAW_PATH: str = "../expt-logs/"

dotenv.load_dotenv()
sys.path.append(os.path.dirname(os.path.abspath('.')))
sys.path.append("..")

from utils import load_agent_logs_df, read_jsonl_as_json, load_game_summary
import datasets, plots, configs, probes, evaluate_utils
from datasets import TruthfulQADataset
from plots import plot_behavior_distribution, plot_roc_curves, add_roc_curves
from configs import config_gpt2, config_phi4
from evaluate_utils import evaluate_probe_on_string, evaluate_probe_on_dataset
import pickle
import importlib

for module in [datasets, plots, configs, probes, evaluate_utils]:
    importlib.reload(module)

config = config_phi4

# probe_path: str = f'checkpoints/tqa_lying_post_gen_probe_{config["short_name"]}.pkl'
probe_path: str = f'checkpoints/dqa_pretend_probe_{config["short_name"]}.pkl'
probe = probes.LinearProbe(config["activation_size"])
with open(probe_path, 'rb') as f:
    probe.model = pickle.load(f).model

model_name = config["model_name"]
load_models: bool = True

if load_models:
    tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(model_name, trust_remote_code=True, device_map="auto")
    device = model.device
    # tqa_dataset = TruthfulQADataset(config, model=model, tokenizer=tokenizer, device=device)
    dqa_dataset = DishonestQADataset(config, model=model, tokenizer=tokenizer, device=device)
    eval(f"model.{config['hook_component']}").register_forward_hook(dqa_dataset.activation_cache.hook_fn)

else:
    model, tokenizer, device = None, None, 'cpu'
    # tqa_dataset = TruthfulQADataset(config, model=model, tokenizer=tokenizer, device=device)
    dqa_dataset = DishonestQADataset(config, model=model, tokenizer=tokenizer, device=device)

EXPT_NAMES: List[str] = ["2025-02-01_phi_phi_100_games_v3",]
DESCRIPTIONS: List[str] = ["Crew: Phi, Imp: Phi",]
summary_logs_paths: List[str] = [
    os.path.join(LOGS_PATH, f"{expt_name}_all_skill_scores.json") for expt_name in EXPT_NAMES
]

summary_dfs: List[DataFrame] = []

for summary_logs_path in summary_logs_paths:
    # read json line by line
    summary_logs: List[Dict[str, Any]] = read_jsonl_as_json(summary_logs_path)
    summary_df: DataFrame = json_normalize(summary_logs)
    # sort by game_index and then step
    summary_df = summary_df.sort_values(by=["game_index", "step"])
    summary_dfs.append(summary_df)
    print(f"Loaded {len(summary_df)} logs from {summary_logs_path}")

summary_df_all_expts = pd.concat([summary_df.assign(experiment=expt_name) for summary_df, expt_name in zip(summary_dfs, EXPT_NAMES)])

EXPT_NAME = "2025-02-01_phi_phi_100_games_v3"
agent_logs_path: str = os.path.join(RAW_PATH, EXPT_NAME + "/agent-logs-compact.json")
agent_logs_df: List[DataFrame] = load_agent_logs_df(agent_logs_path)

def agent_logs_row_to_full_prompt(row: pd.Series) -> str:
    system_prompt = row["interaction.system_prompt"]
    summarization = row["interaction.prompt.Summarization"]
    processed_memory = row["interaction.prompt.Memory"]
    phase = row["interaction.prompt.Phase"]
    all_info = row["interaction.prompt.All Info"]

    user_prompt = f"Summarization: {summarization}\n\n{all_info}\n\nMemory: {processed_memory}\
                    \n\nPhase: {phase}. Return your output."

    assistant_prompt = row["interaction.full_response"]

    phi_format_sample_text = f'''<|im_start|>system<|im_sep|>{system_prompt}<|im_end|><|im_start|>user<|im_sep|>{user_prompt}<|im_end|>\
<|im_start|>assistant<|im_sep|>{assistant_prompt}<|im_end|>'''

    return phi_format_sample_text

json_outputs = []
eval_rows_num = agent_logs_df.shape[0]
# eval_rows_num = 30

for i in range(0, eval_rows_num):
    full_prompts = agent_logs_row_to_full_prompt(agent_logs_df.iloc[i])
    probe_output, probe_outputs = evaluate_probe_on_string(full_prompts, model, tokenizer, probe, dqa_dataset, device)
    
    if i % (eval_rows_num // 10) == 0:
        print(f"Evaluated {i}/{eval_rows_num} rows, predicted {probe_output}")

    json_output = {
        "game_index": int(agent_logs_df.iloc[i]["game_index"].split(" ")[1]) if isinstance(agent_logs_df.iloc[i]["game_index"], str) else int(agent_logs_df.iloc[i]["game_index"]),
        "step": int(agent_logs_df.iloc[i]["step"]),
        "player_name": agent_logs_df.iloc[i]["player.name"],
        "probe_output": probe_output
    }
    json_outputs.append(json_output)


# store the probe outputs into './probe_outputs/pretend_{EXPT_NAME}.json'
with open(f'../linear-probes/probe_outputs/pretend_{EXPT_NAME}.json', 'w') as f:
    json.dump(json_outputs, f)
    print(f"Saved {len(json_outputs)} probe outputs to './probe_outputs/pretend_{EXPT_NAME}.json'")

print("Done!")