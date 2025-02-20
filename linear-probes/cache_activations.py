import sys
from transformers import AutoTokenizer, AutoModelForCausalLM
import torch as t
import importlib
import os

sys.path.append(os.path.dirname(os.path.abspath('.')))

import datasets, plots, configs, evaluate_utils
for module in [datasets, plots, configs, evaluate_utils]:
    importlib.reload(module)

from datasets import AmongUsDataset
from configs import config_phi4

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

dataset = AmongUsDataset(config, model=model, tokenizer=tokenizer, device=device, expt_name=EXPT_NAME, test_split=1.0)
eval(f"model.{config['hook_component']}").register_forward_hook(dataset.activation_cache.hook_fn)

dataset.populate_dataset(force_redo=True, max_rows=0, batched=False, seq_len=config["seq_len"], num_tokens=None)
print(f'Done! Cached activations for {len(dataset.agent_logs_df)} rows.')