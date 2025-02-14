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

from transformers import AutoTokenizer, AutoModelForCausalLM
import pandas as pd
import torch as t
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
import numpy as np
from torch.utils.data import Dataset, DataLoader, random_split
from typing import Tuple, List, Optional
import os
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split
from pprint import pprint as pp

sys.path.append("..")

from utils import load_agent_logs_df, read_jsonl_as_json, load_game_summary

LOGS_PATH: str = "../evaluations/results/"
RAW_PATH: str = "../expt-logs/"

import dotenv
dotenv.load_dotenv()

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

    phi_format_sample_text = f'''<|im_start|>system<|im_sep|>{system_prompt}<|im_end|><|im_start|>user<|im_sep|>{user_prompt}<|im_end|><|im_start|>assistant<|im_sep|>{assistant_prompt}<|im_end|>'''

    return phi_format_sample_text

model_name = "microsoft/phi-4"

tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True, force_download=False)
phi_4 = AutoModelForCausalLM.from_pretrained(model_name, trust_remote_code=True, device_map="auto", force_download=False)

path_probe: str = '../probes/checkpoints/tqa_lying_post_generation_probe.pt'

class LogisticRegressionModel(nn.Module):
    def __init__(self, input_dim):
        super().__init__()
        self.linear = nn.Linear(input_dim, 1)  

    def forward(self, x):
        return t.sigmoid(self.linear(x))

probe = LogisticRegressionModel(input_dim=5120)
probe.load_state_dict(t.load(path_probe))

class LyingProbeEvaluatorHook:
    def __init__(self, model, tokenizer, probe):
        self.model = model
        self.tokenizer = tokenizer
        self.activations = []
        self.probe = probe
        self.probe_outputs = []
        self.handles = []

    def register_hook(self, layer):
        handle = layer.register_forward_hook(self.hook_fn)
        self.handles.append(handle)

    def hook_fn(self, module, input, output):
        activations = output.detach().cpu()[0][-1]
        activations = t.Tensor(activations.reshape(1, -1))
        probe_output = self.probe(activations)
        self.probe_outputs.append(float(probe_output))

    def remove_hooks(self):
        for handle in self.handles:
            handle.remove()

try:
    lying_probe_evaluator.remove_hooks()
    print("Removed lying_probe_evaluator hooks")
except:
    print("No lying_probe_evaluator hooks to remove")

lying_probe_evaluator = LyingProbeEvaluatorHook(phi_4, tokenizer, probe)

layer: int = 15

component = phi_4.model.layers[layer].mlp
lying_probe_evaluator.register_hook(component)

def clear_gpu_memory():
    # Clear CUDA cache from all GPUs
    import gc

    # Empty CUDA cache 
    t.cuda.empty_cache()

    # Run garbage collector
    gc.collect()

    # Clear memory on all CUDA devices
    for i in range(t.cuda.device_count()):
        with t.cuda.device(f'cuda:{i}'):
            t.cuda.empty_cache()
            t.cuda.ipc_collect()

# clear the gpu memory and lying probe evaluator
clear_gpu_memory()
lying_probe_evaluator.probe_outputs = []
json_outputs = []

for i in range(0, agent_logs_df.shape[0]):
    clear_gpu_memory()
    
    # Process batch of prompts
    full_prompts = agent_logs_row_to_full_prompt(agent_logs_df.iloc[i])
    # Set padding direction before tokenizing
    tokens = tokenizer.encode(full_prompts, return_tensors="pt").to(phi_4.device)
    
    phi_4.generate(tokens, max_new_tokens=1)
    
    print(f"Evaluated {i}/{agent_logs_df.shape[0]} row, predicted {lying_probe_evaluator.probe_outputs[-1]}")

    json_output = {
        "game_index": int(agent_logs_df.iloc[i]["game_index"].split(" ")[1]) if isinstance(agent_logs_df.iloc[i]["game_index"], str) else int(agent_logs_df.iloc[i]["game_index"]),
        "step": int(agent_logs_df.iloc[i]["step"]),
        "player_name": agent_logs_df.iloc[i]["player.name"],
        "probe_output": lying_probe_evaluator.probe_outputs[-1]
    }
    json_outputs.append(json_output)

    # save after every 1000 rows
    if i % 1000 == 0:
        with open(f'../probes/probe_outputs/post_gen_{EXPT_NAME}.json', 'w') as f:
            json.dump(json_outputs, f)

# store the probe outputs into './probe_outputs/post_gen_{EXPT_NAME}.json'
with open(f'../probes/probe_outputs/post_gen_{EXPT_NAME}.json', 'w') as f:
    json.dump(json_outputs, f)

print(f"EXPERIMENT COMPLETE!")