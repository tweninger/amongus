# train and evaluate logistic probes on all datasets (and get results for the paper)
# NOTE: this assumes all activations have already been cached (run cache_activations.py first)

################### SETUP

import os
import sys
import pickle
from typing import Dict, Any, List

sys.path.append(os.path.dirname(os.path.abspath('.')))
sys.path.append('.')

from datasets import (
    TruthfulQADataset,
    DishonestQADataset, 
    AmongUsDataset,
    RepEngDataset,
)
from probes import LinearProbe

config_phi4_linear_probe: Dict[str, Any] = {
    "short_name": "phi4",
    "model_name": "microsoft/phi-4",
    "activation_size": 5120,
    "seq_len": 16384,
    "hook_component": "model.layers[20].mlp",
    "test_split": 0.2,
    "batch_size": 32,
    "learning_rate": 0.001,
    "probe_training_epochs": 4,
    "probe_training_batch_size": 32,
    "probe_training_learning_rate": 0.001,
    "probe_training_num_tokens": 10,
    "probe_training_chunk_idx": 0,
}

datasets: List[str] = [
    "TruthfulQADataset",
    "DishonestQADataset",
    "AmongUsDataset",
    "RepEngDataset",
]

config = config_phi4_linear_probe
model, tokenizer, device = None, None, 'cpu'
amongus_expt_name: str = "2025-02-01_phi_phi_100_games_v3"

################### TRAINING PROBES

for dataset_name in datasets:
    print(f"Loading {dataset_name}...")
    dataset = eval(f"{dataset_name}")(
        config, 
        model=model,
        tokenizer=tokenizer, 
        device=device, 
        test_split=0.2, 
        expt_name=amongus_expt_name
        )
    train_loader = dataset.get_train(
        batch_size=config["probe_training_batch_size"],
        num_tokens=config["probe_training_num_tokens"],
        chunk_idx=config["probe_training_chunk_idx"],
    )
    probe = LinearProbe(
        input_dim=dataset.activation_size, 
        device=device, 
        lr=config["probe_training_learning_rate"]
        )
    print(f'Training probe on {len(train_loader)} batches and {len(train_loader.dataset)} samples.')
    probe.fit(train_loader, epochs=config["probe_training_epochs"])

    checkpoint_path = f'checkpoints/{dataset_name}_probe_{config["short_name"]}.pkl'
    with open(checkpoint_path, 'wb') as f:
        pickle.dump(probe, f)
        print(f"Probe saved to {checkpoint_path}")

print(f"Probes trained and saved for all datasets.")