import asyncio
import sys
from collections import deque
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
HUMAN_TRIALS = ROOT / "human_trials"

if str(HUMAN_TRIALS) not in sys.path:
    sys.path.insert(0, str(HUMAN_TRIALS))

from amongagents.envs.action import MoveTo  # noqa: E402
from amongagents.envs.configs.game_config import FIVE_MEMBER_GAME  # noqa: E402
from amongagents.envs.game import AmongUs  # noqa: E402
from models import WebPlayerAgent  # noqa: E402
from server import (  # noqa: E402
    GameRoom,
    _human_map_action_interval,
    _matching_current_task_action,
    _record_human_map_action,
    build_realtime_game_config,
    execute_realtime_task_action,
)


def test_realtime_game_config_uses_high_action_safety_limit():
    config = build_realtime_game_config({"num_players": 5, "max_timesteps": 20})

    assert config["max_timesteps"] > 500


def test_realtime_action_validation_rejects_stale_move():
    game = AmongUs(
        game_config=dict(FIVE_MEMBER_GAME),
        agent_config={
            "Impostor": "LLM",
            "Crewmate": "LLM",
            "IMPOSTOR_LLM_CHOICES": ["gemini/test-model"],
            "CREWMATE_LLM_CHOICES": ["gemini/test-model"],
        },
    )
    game.initialize_game()
    player = game.players[0]
    game.check_actions()
    available_move = next(action for action in player.get_available_actions() if action.name == "MOVE")

    assert _matching_current_task_action(game, player, available_move).new_location == available_move.new_location

    stale_move = MoveTo(player.location, "Not a room")
    assert _matching_current_task_action(game, player, stale_move) is None

    skipped_move = MoveTo(player.location, player.location)
    assert _matching_current_task_action(game, player, skipped_move) is None


def test_ai_interval_tracks_human_action_intervals(monkeypatch):
    room = SimpleNamespace(
        human_map_action_intervals=deque(maxlen=40),
        human_last_map_action_at={},
    )
    player = SimpleNamespace(name="Purple")
    monotonic_times = iter([100.0, 108.0, 120.0])
    monkeypatch.setattr("server.time.monotonic", lambda: next(monotonic_times))

    _record_human_map_action(room, player)
    _record_human_map_action(room, player)
    _record_human_map_action(room, player)

    assert list(room.human_map_action_intervals) == [8.0, 12.0]
    assert _human_map_action_interval(room) == pytest.approx(10.0)


def test_human_map_action_executes_without_waiting_for_other_players():
    game = AmongUs(
        game_config=dict(FIVE_MEMBER_GAME),
        agent_config={
            "Impostor": "LLM",
            "Crewmate": "LLM",
            "IMPOSTOR_LLM_CHOICES": ["gemini/test-model"],
            "CREWMATE_LLM_CHOICES": ["gemini/test-model"],
        },
    )
    game.initialize_game()
    game.agents[0] = WebPlayerAgent(game.players[0])
    room = GameRoom(dict(FIVE_MEMBER_GAME), len(game.players), "host", "yellow")
    room.game_instance = game
    game.check_actions()
    move = next(action for action in game.players[0].get_available_actions() if action.name == "MOVE")

    asyncio.run(execute_realtime_task_action(room, game.agents[0], move))

    assert game.players[0].location == move.new_location
    assert game.timestep == 1


def test_ghost_can_move_after_being_killed_in_realtime_gameplay():
    game = AmongUs(
        game_config=dict(FIVE_MEMBER_GAME),
        agent_config={
            "Impostor": "LLM",
            "Crewmate": "LLM",
            "IMPOSTOR_LLM_CHOICES": ["gemini/test-model"],
            "CREWMATE_LLM_CHOICES": ["gemini/test-model"],
        },
    )
    game.initialize_game()
    game.agents[0] = WebPlayerAgent(game.players[0])
    room = GameRoom(dict(FIVE_MEMBER_GAME), len(game.players), "host", "yellow")
    room.game_instance = game

    ghost = game.players[0]
    ghost.is_alive = False
    ghost.killed_this_step = True
    game.check_actions()
    move = next(action for action in ghost.get_available_actions() if action.name == "MOVE")

    asyncio.run(execute_realtime_task_action(room, game.agents[0], move))

    assert ghost.location == move.new_location
    assert game.timestep == 1
