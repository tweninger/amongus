from torch.utils.data import Dataset, DataLoader, random_split
import torch as t
from typing import List, Tuple, Dict, Any
import pickle
import pandas as pd
import os

class ActivationCache:
    def __init__(self, model, tokenizer, device):
        self.model = model
        self.tokenizer = tokenizer
        self.device = device
        self.activations = []
        self.handles = []

    def hook_fn(self, module, input, output):
        self.activations.append(output.detach().cpu().numpy())

    def register_hook(self, layer):
        handle = layer.register_forward_hook(self.hook_fn)
        self.handles.append(handle)
        
    def clear_activations(self):
        self.activations = []

    def remove_hooks(self):
        for handle in self.handles:
            handle.remove()

class ActivationDataset(Dataset):
    def __init__(self, test_split: float = 0.2, name: str = "", model=None, tokenizer=None, device=None, activation_size: int = 768):
        """
        Initialize empty dataset with configurable test split ratio
        
        Args:
            test_split (float): Proportion of data to use for testing (0-1)
        """
        self.data: List[Tuple[t.Tensor, int]] = []
        self.test_split = test_split
        self.name = name
        self.model = model
        self.tokenizer = tokenizer
        self.device = device
        self.activation_size = activation_size
        self.activation_cache = ActivationCache(model, tokenizer, device)
        # if model is passed, remove all hooks from the model
        if model is not None:
            self.activation_cache.remove_hooks()

    def append(self, x: t.Tensor, y: int) -> None:
        """
        Add a new (x,y) pair to the dataset
        
        Args:
            x (t.Tensor): Input tensor of size 5120
            y (int): Binary label (0 or 1)
        """
        assert x.shape[0] == self.activation_size, f"Expected x to have size {self.activation_size}, got {x.shape[0]}"
        assert y in [0, 1], f"y must be binary (0 or 1), got {y}"
        self.data.append((x, y))
        
    def __len__(self) -> int:
        return len(self.data)
        
    def __getitem__(self, idx: int) -> Tuple[t.Tensor, int]:
        return self.data[idx]
    
    def get_splits(self, batch_size: int = 32, shuffle: bool = True,
                  num_workers: int = 0, pin_memory: bool = True) -> Tuple[DataLoader, DataLoader]:
        """
        Get train and test DataLoaders
        
        Args:
            batch_size (int): How many samples per batch to load
            shuffle (bool): Whether to shuffle the data
            num_workers (int): How many subprocesses to use for data loading
            pin_memory (bool): If True, the data loader will copy Tensors into CUDA pinned memory
            
        Returns:
            tuple: (train_loader, test_loader)
        """
        test_size = int(len(self) * self.test_split)
        train_size = len(self) - test_size
        
        train_dataset, test_dataset = random_split(
            self, 
            [train_size, test_size],
            generator=t.Generator().manual_seed(42)
        )
        
        train_loader = DataLoader(
            train_dataset,
            batch_size=batch_size,
            shuffle=shuffle,
            num_workers=num_workers,
            pin_memory=pin_memory
        )
        
        test_loader = DataLoader(
            test_dataset,
            batch_size=batch_size,
            shuffle=False,
            num_workers=num_workers,
            pin_memory=pin_memory
        )
        
        return train_loader, test_loader
    
    def get_stats(self) -> dict:
        """
        Get basic statistics about the dataset
        
        Returns:
            dict: Statistics including total samples and class distribution
        """
        if not self.data:
            return {"total_samples": 0, "class_distribution": {}}
            
        labels = [y for _, y in self.data]
        unique, counts = t.tensor(labels).unique(return_counts=True)
        class_dist = dict(zip(unique.tolist(), counts.tolist()))
        
        return {
            "total_samples": len(self),
            "class_distribution": class_dist
        }

    def save(self):
        with open(self.activations_path, 'wb') as f:
            pickle.dump(self.data, f)
            print(f"Saved activations to {self.activations_path}")
    def load(self):
        with open(self.activations_path, 'rb') as f:
            self.data = pickle.load(f)
            print(f"Loaded activations from {self.activations_path}")
class TruthfulQADataset(ActivationDataset):
    def __init__(self, config: Dict[str, Any], model=None, tokenizer=None, device=None):
        super().__init__(config["test_split"], config["dataset_name"], model, tokenizer, device, config["activation_size"])
        self.name: str = config["dataset_name"]
        self.data_path: str = './data/TruthfulQA/TruthfulQA.csv'
        self.tqa_df = pd.read_csv(self.data_path)
        self.activations_path: str = f'./data/{self.name}_{config["short_name"]}_acts.pkl'

    def row_to_prompts(self, row: pd.Series) -> str:
        question = row['Question']
        best_answer = row['Best Answer']
        best_incorrect_answer = row['Best Incorrect Answer']
        phi_format_correct_qa = f'''<|im_start|>user<|im_sep|>{question}<|im_end|><|im_start|>assistant<|im_sep|>{best_answer}<|im_end|>'''
        phi_format_incorrect_qa = f'''<|im_start|>user<|im_sep|>{question}<|im_end|><|im_start|>assistant<|im_sep|>{best_incorrect_answer}<|im_end|>'''
        return phi_format_correct_qa, phi_format_incorrect_qa

    def populate_dataset_with_row(self, row):
        correct_prompt, incorrect_prompt = self.row_to_prompts(row)
        correct_tokens = self.tokenizer.encode(correct_prompt, return_tensors="pt").to(self.device)
        self.activation_cache.clear_activations()
        with t.no_grad():
            self.model(correct_tokens)
            correct_activations = self.activation_cache.activations[0][0][-1]
            self.append(correct_activations, 1)
            incorrect_tokens = self.tokenizer.encode(incorrect_prompt, return_tensors="pt").to(self.device)
            self.model(incorrect_tokens)
            incorrect_activations = self.activation_cache.activations[0][0][-1]
            self.append(incorrect_activations, 0)

    def populate_dataset(self):
        # if activations exist, load them
        if os.path.exists(self.activations_path):
            self.data = pickle.load(open(self.activations_path, 'rb'))
        else:
            for idx, row in self.tqa_df.iterrows():
                self.populate_dataset_with_row(row)
                if idx % (len(self.tqa_df) // 10) == 0:
                    print(f"Populated {idx} rows of {len(self.tqa_df)}")
            self.save()