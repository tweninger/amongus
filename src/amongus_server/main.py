"""Stable ASGI import path for local development and production deployment.

The game server still lives in ``human_trials/server.py`` while the project is
being regularized. This module makes that existing app importable as
``amongus_server.main:app`` without relying on systemd-level PYTHONPATH setup.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HUMAN_TRIALS = REPO_ROOT / "human_trials"
AMONG_AGENTS = REPO_ROOT / "among-agents"

for path in (HUMAN_TRIALS, AMONG_AGENTS, REPO_ROOT):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from server import app  # noqa: E402

__all__ = ["app"]

