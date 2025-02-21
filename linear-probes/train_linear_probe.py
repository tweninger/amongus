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

def train_probe(dataset_name: str, num_tokens: int):
    config = config_phi4
    model_name = config["model_name"]
    model, tokenizer, device = None, None, 'cpu'
    dataset = eval(f"{dataset_name}")(config, model=model, tokenizer=tokenizer, device=device, test_split=0.2)
    dataset.populate_dataset(force_redo=False)
    train_loader = dataset.get_train(batch_size=32, num_tokens=num_tokens) # taking the last num_tokens activations
    probe = LinearProbe(input_dim=dataset.activation_size, device=device)

    print(f'Training probe on {len(train_loader)} batches and {len(train_loader.dataset)} samples.')

    probe.fit(train_loader, epochs=100)

    checkpoint_path = f'checkpoints/{dataset_name}_probe_{config["short_name"]}.pkl'
    with open(checkpoint_path, 'wb') as f:
        pickle.dump(probe, f)
        print(f"Probe saved to {checkpoint_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--dataset', type=str, default="DishonestQADataset",
                      help='Name of dataset class to use')
    parser.add_argument('--num_tokens', type=int, default=10,
                      help='Number of tokens to use for training')
    args = parser.parse_args()
    train_probe(args.dataset, args.num_tokens)