import os
import sys
import pickle
import argparse
from transformers import AutoModelForCausalLM, AutoTokenizer

sys.path.append(os.path.dirname(os.path.abspath('.')))
import configs
from datasets import TruthfulQADataset, DishonestQADataset, AmongUsDataset
from probes import LinearProbe

from configs import config_phi4

def train_probe(dataset_name: str):
    config = config_phi4
    model_name = config["model_name"]
    load_models: bool = False

    if load_models:
        tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
        model = AutoModelForCausalLM.from_pretrained(model_name, trust_remote_code=True, device_map="auto")
        device = model.device
        dataset = eval(f"{dataset_name}")(config, model=model, tokenizer=tokenizer, device=device)
        eval(f"model.{config['hook_component']}").register_forward_hook(dataset.activation_cache.hook_fn)
    else:
        model, tokenizer, device = None, None, 'cpu'
        dataset = eval(f"{dataset_name}")(config, model=model, tokenizer=tokenizer, device=device)

    dataset.populate_dataset(force_redo=False)

    print(f'Training linear probe on {dataset_name} dataset with {len(dataset)} datapoints.')

    train_loader = dataset.get_train(batch_size=32)
    probe = LinearProbe(input_dim=dataset.activation_size, device=device)

    probe.fit(train_loader, epochs=300)

    checkpoint_path = f'checkpoints/{dataset_name}_probe_{config["short_name"]}.pkl'
    with open(checkpoint_path, 'wb') as f:
        pickle.dump(probe, f)
        print(f"Probe saved to {checkpoint_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--dataset', type=str, default="DishonestQADataset",
                      help='Name of dataset class to use')
    args = parser.parse_args()
    
    train_probe(args.dataset)