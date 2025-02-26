import sys
import argparse
from transformers import AutoTokenizer, AutoModelForCausalLM
import torch as t
import importlib
import os

sys.path.append(os.path.dirname(os.path.abspath('.')))

import datasets, plots, configs, evaluate_utils
for module in [datasets, plots, configs, evaluate_utils]:
    importlib.reload(module)

from datasets import AmongUsDataset, TruthfulQADataset, DishonestQADataset, RepEngDataset, RolePlayingDataset, ApolloProbeDataset
from configs import config_phi4, config_gpt2

def main(dataset_name: str):
    config = config_phi4
    model_name = config["model_name"]
    load_models = True

    if load_models:
        tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
        model = AutoModelForCausalLM.from_pretrained(model_name, trust_remote_code=True, device_map="auto")
        device = model.device
    else:
        model, tokenizer, device = None, None, 'cpu'

    # Create dataset based on the provided name
    if dataset_name == "AmongUsDataset":
        dataset = eval(dataset_name)(config, model=model, tokenizer=tokenizer, device=device, 
                                    expt_name="2025-02-01_phi_phi_100_games_v3", test_split=1.0)
    else:
        dataset = eval(dataset_name)(config, model=model, tokenizer=tokenizer, device=device, test_split=1.0)
    
    eval(f"model.{config['hook_component']}").register_forward_hook(dataset.activation_cache.hook_fn)
    num_tokens = 5 if dataset_name == "ApolloProbeDataset" else None
    dataset.populate_dataset(force_redo=True, max_rows=0, seq_len=config["seq_len"], num_tokens=num_tokens, chunk_size=100)
    print(f'Done! Cached activations for {dataset.num_total_chunks} chunks.')

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Cache activations for a dataset')
    parser.add_argument('--dataset', type=str, default="DishonestQADataset",
                        choices=["AmongUsDataset", "TruthfulQADataset", "DishonestQADataset", 
                                "RepEngDataset", "RolePlayingDataset", "ApolloProbeDataset"],
                        help='Name of dataset class to use')
    args = parser.parse_args()
    main(args.dataset)