import torch

from AmongUs.training import NeuralNetwork


def test_neural_network():
    model = NeuralNetwork()
    assert isinstance(model, torch.nn.Module)
