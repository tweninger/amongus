# AmongUs

This project focuses on making open-weight LLM agents play the game "Among Us" and studying how these models learn to express lying and deception within the context of the game.

## Overview

The aim is to simulate the popular multiplayer game "Among Us" using AI agents and analyze their behavior, particularly their ability to deceive and lie, which is central to the game's mechanics.

![Among Us](https://static.wikia.nocookie.net/among-us-wiki/images/f/f5/Among_Us_space_key_art_redesign.png)

## Features

TODO: Add later after progress on the project.

## Project Structure

```plaintext
.
├── CONTRIBUTING.md         # Contribution guidelines
├── Dockerfile               # Docker setup for project environment
├── LICENSE                  # License information
├── README.md                # Project documentation (this file)
├── among-agents             # Main code for the Among Us agents
│   ├── README.md            # Documentation for agent implementation
│   ├── amongagents          # Core agent and environment modules
│   ├── envs                 # Game environment and configurations
│   ├── evaluation           # Evaluation scripts for agent performance
│   ├── notebooks            # Jupyter notebooks for running experiments
│   ├── requirements.txt     # Python dependencies for agents
│   └── setup.py             # Setup script for agent package
├── expt-logs                # Experiment logs
├── k8s                      # Kubernetes configurations for deployment
├── main.py                  # Main entry point for running the game
├── notebooks                # Additional notebooks (not part of the main project)
├── reports                  # Experiment reports
├── requirements.txt         # Python dependencies for main project
├── tests                    # Unit tests for project functionality
└── utils.py                 # Utility functions
```

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/7vik/AmongUs.git
   cd AmongUs
   ```

2. Set up the environment:
   ```bash
   conda create -n amongus python=3.10
   conda activate amongus
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Usage

To run the game simulation:

```bash
python main.py
```

For running an evaluation report:

```bash
jupyter notebook reports/XYZ.ipynb
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for details on how to contribute to this project.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Using and building up on [AmongAgents](https://github.com/cyzus/among-agents).

For anything, please contact Satvik Golechha (7vik) at zsatvik@gmail.com.
