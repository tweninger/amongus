import os
import sys
import json
import numpy as np
import requests
import pandas as pd
from typing import List, Dict, Any, Tuple, Union, Optional
from transformers import AutoTokenizer, AutoModelForCausalLM
import torch as t
from torch.utils.data import Dataset, DataLoader, random_split
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split
from pprint import pprint as pp
import importlib
import pickle

sys.path.append(os.path.dirname(os.path.abspath('.')))

import datasets, plots, configs, probes, evaluate_utils
for module in [datasets, plots, configs, probes, evaluate_utils]:
    importlib.reload(module)

from datasets import AmongUsDataset
from plots import plot_behavior_distribution, plot_roc_curves, add_roc_curves, print_metrics, plot_roc_curve_eval
from configs import config_phi4
from evaluate_utils import evaluate_probe_on_string, evaluate_probe_on_dataset, evaluate_probe_on_activation_dataset
from utils import load_agent_logs_df, read_jsonl_as_json, load_game_summary

config = config_phi4
model_name = config["model_name"]
load_models = True

if load_models:
    tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(model_name, trust_remote_code=True, device_map="auto")
    device = model.device
else:
    model, tokenizer, device = None, None, 'cpu'

LOGS_PATH, RAW_PATH = "../evaluations/results/", "../expt-logs/"
sys.path.append("..")
EXPT_NAME, DESCRIPTIONS = "2025-02-01_phi_phi_100_games_v3", "Crew: Phi, Imp: Phi"

dataset = AmongUsDataset({**config, "test_split": 1.0}, model=model, tokenizer=tokenizer, device=device, expt_name=EXPT_NAME)
eval(f"model.{config['hook_component']}").register_forward_hook(dataset.activation_cache.hook_fn)

dataset.populate_dataset(force_redo=True, max_rows=0)
print(f'Done! Cached activations for {len(dataset.agent_logs_df)} rows.')