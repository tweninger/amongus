import sys

from farconf import parse_cli

from AmongUs.configs import RunConfig
from AmongUs.training import train
from AmongUs.utils.tracking import setup_wandb


def main(config: RunConfig):
    setup_wandb(config)
    train(config.training)


if __name__ == "__main__":
    # Allow default name for manually run experiments (not for batch experiments).
    args = ["experiment_name=default_experiment"] + sys.argv[1:]

    config = parse_cli(args, RunConfig)
    main(config=config)
