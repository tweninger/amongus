# EVALUATE ALL LINEAR PROBES (AND GET PLOTS FOR PAPER)

import sys
import pickle
sys.path.append('.')
import torch as t
import json
import pandas as pd
from pandas import DataFrame, json_normalize
from tqdm import tqdm
import os
import numpy as np
from typing import Dict, Any, List, Tuple
from sklearn.metrics import roc_curve, auc, precision_recall_curve, average_precision_score

from datasets import TruthfulQADataset, DishonestQADataset, AmongUsDataset, RolePlayingDataset, RepEngDataset
from evaluate_utils import evaluate_probe_on_activation_dataset
from configs import config_phi4
from plots import plot_behavior_distribution, plot_roc_curves, add_roc_curves, print_metrics, plot_roc_curve_eval
import probes
from pprint import pprint as pp

config = config_phi4

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
    "probe_training_epochs": 10,
    "probe_training_batch_size": 32,
    "probe_training_learning_rate": 0.001,
    "probe_training_num_tokens": 5,
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

def evaluate_probe(
    dataset_name: str, 
    probe: LinearProbe,
    config: Dict[str, Any], 
    model=None, 
    tokenizer= None
    ) -> None:

    rocs = {}
    
    # evaluate on TQA
    dataset = TruthfulQADataset(config, model=model, tokenizer=tokenizer, device=device, test_split=0.2)
    test_acts_chunk = dataset.get_test_acts()
    av_probe_outputs, accuracy = evaluate_probe_on_activation_dataset(
        chunk_data=test_acts_chunk,
        probe=probe,
        device=device,
        num_tokens=None,
    )
    labels = t.tensor([batch[1] for batch in test_acts_chunk]).numpy()
    fig, roc = plot_roc_curve_eval(labels, av_probe_outputs)
    rocs["TQA"] = roc
    # save the figure in high-res PDF
    fig.savefig(f"results/{dataset_name}_probe_{config['short_name']}_TQA.pdf", dpi=300)

    # evaluate on DQA
    dataset = DishonestQADataset(config, model=model, tokenizer=tokenizer, device=device, test_split=0.2)
    test_acts_chunk = dataset.get_test_acts()
    av_probe_outputs, accuracy = evaluate_probe_on_activation_dataset(
        chunk_data=test_acts_chunk,
        probe=probe,
        device=device,
        num_tokens=None,
    )
    labels = t.tensor([batch[1] for batch in test_acts_chunk]).numpy()
    fig, roc = plot_roc_curve_eval(labels, av_probe_outputs)
    rocs["DQA"] = roc
    # save the figure in high-res PDF
    fig.savefig(f"results/{dataset_name}_probe_{config['short_name']}_DQA.pdf", dpi=300)

    # evaluate on RepEng
    dataset = RepEngDataset(config, model=model, tokenizer=tokenizer, device=device, test_split=0.2)
    test_acts_chunk = dataset.get_test_acts()
    av_probe_outputs, accuracy = evaluate_probe_on_activation_dataset(
        chunk_data=test_acts_chunk,
        probe=probe,
        device=device,
        num_tokens=None,
    )
    labels = t.tensor([batch[1] for batch in test_acts_chunk]).numpy()
    fig, roc = plot_roc_curve_eval(labels, av_probe_outputs)
    rocs["RepEng"] = roc
    # save the figure in high-res PDF
    fig.savefig(f"results/{dataset_name}_probe_{config['short_name']}_RepEng.pdf", dpi=300)

    # evaluate on AmongUs

    



if __name__ == "__main__":
    for probe_dataset_name in datasets:
        print(f"Evaluating probe trained on {probe_dataset_name}...")
        probe = LinearProbe(config["activation_size"])

        with open(f'checkpoints/{probe_dataset_name}_probe_{config["short_name"]}.pkl', 'rb') as f:
            probe.model = pickle.load(f).model
            print(f'Loaded probe trained on {probe_dataset_name}.')
        
        rocs = evaluate_probe(probe_dataset_name, probe, config)
        print(rocs)