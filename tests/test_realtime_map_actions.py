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
    AI_MAX_ACTION_INTERVAL_SECONDS,
    AI_MIN_ACTION_INTERVAL_SECONDS,
    KILL_COOLDOWN_SECONDS,
    GameRoom,
    _action_cooldown_seconds_left,
    _human_map_action_interval,
    _is_silence_message,
    _matching_current_task_action,
    _record_human_map_action,
    _route_task_started_observation,
    _start_action_cooldown,
    add_kill_event,
    add_vent_event,
    build_realtime_game_config,
    execute_realtime_task_action,
    pause_match_clock,
    resume_match_clock,
)


def test_realtime_game_config_uses_high_action_safety_limit():
    config = build_realtime_game_config({"num_players": 5, "max_timesteps": 20})

    assert config["max_timesteps"] > 500


def test_ai_context_reports_match_time_in_minutes():
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
    game.match_seconds_left = 150
    game.match_duration_seconds = 600
    game.update_map()

    assert "Match time remaining: 2.5 minutes of 10.0 minutes total." in game.players[0].location_info
    assert "Action sequence:" not in game.players[0].location_info


@pytest.mark.parametrize("message", ["SILENCE", "SPEAK: SILENCE", '[Action] SPEAK: "SILENCE"'])
def test_silence_messages_are_not_sent_to_discussion(message):
    assert _is_silence_message(message)


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
    assert _human_map_action_interval(room) == pytest.approx(
        min(AI_MAX_ACTION_INTERVAL_SECONDS, max(AI_MIN_ACTION_INTERVAL_SECONDS, 10.0))
    )


def test_realtime_kill_cooldown_uses_elapsed_seconds(monkeypatch):
    room = SimpleNamespace(kill_cooldown_deadlines={}, vent_cooldown_deadlines={})
    player = SimpleNamespace(name="Player 4: lime", kill_cooldown=3)
    monotonic_time = [100.0]
    monkeypatch.setattr("server.time.monotonic", lambda: monotonic_time[0])

    _start_action_cooldown(room, player, "KILL")
    assert player.kill_cooldown == 0
    assert _action_cooldown_seconds_left(room, player, "KILL") == KILL_COOLDOWN_SECONDS

    monotonic_time[0] = 100.0 + KILL_COOLDOWN_SECONDS - 0.9
    assert _action_cooldown_seconds_left(room, player, "KILL") == 1
    monotonic_time[0] = 100.0 + KILL_COOLDOWN_SECONDS
    assert _action_cooldown_seconds_left(room, player, "KILL") == 0


def test_task_start_is_observed_by_players_in_the_same_room():
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
    actor, witness, elsewhere = game.players[:3]
    actor.location = "Cafeteria"
    witness.location = "Cafeteria"
    elsewhere.location = "Admin"

    _route_task_started_observation(game, actor, "Fix Wiring")

    assert "started working on Fix Wiring" in witness.observation_history[-1]
    assert elsewhere.observation_history == []


def test_vent_event_identifies_the_venter_and_rooms():
    room = SimpleNamespace(vent_events=[], next_vent_event_id=1)
    player = SimpleNamespace(name="Player 4: lime")

    add_vent_event(room, player, "Security", "Electrical")

    assert room.vent_events == [{
        "id": 1,
        "player_color": "lime",
        "source_room": "security",
        "destination_room": "electrical",
    }]


def test_kill_event_identifies_the_killer_target_and_room():
    room = SimpleNamespace(kill_events=[], next_kill_event_id=1)
    killer = SimpleNamespace(name="Player 4: lime")
    target = SimpleNamespace(name="Player 1: black")

    add_kill_event(room, killer, target, "Cafeteria")

    assert room.kill_events == [{
        "id": 1,
        "killer_color": "lime",
        "target_color": "black",
        "room": "cafeteria",
    }]


def test_match_clock_preserves_remaining_time_during_meeting(monkeypatch):
    room = SimpleNamespace(
        match_deadline_monotonic=135.0,
        match_seconds_remaining=500.0,
        game_finished=False,
    )
    monotonic_times = iter([100.0, 200.0])
    monkeypatch.setattr("server.time.monotonic", lambda: next(monotonic_times))

    pause_match_clock(room)
    resume_match_clock(room)

    assert room.match_seconds_remaining == pytest.approx(35.0)
    assert room.match_deadline_monotonic == pytest.approx(235.0)


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
