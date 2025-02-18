from typing import Dict, Any

config_gpt2: Dict[str, Any] = {
    "short_name": "gpt2",
    "model_name": "openai-community/gpt2",
    "activation_size": 768,
    "hook_component": "transformer.h[6].mlp",
    "test_split": 0.2,
    "batch_size": 32,
    "learning_rate": 0.001,
    }

config_phi4: Dict[str, Any] = {
    "short_name": "phi4",
    "model_name": "microsoft/phi-4",
    "activation_size": 5120,
    "hook_component": "model.layers[15].mlp",
    "test_split": 0.2,
    "batch_size": 32,
    "learning_rate": 0.001,
}