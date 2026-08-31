import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HUMAN_TRIALS = ROOT / "human_trials"

if str(HUMAN_TRIALS) not in sys.path:
    sys.path.insert(0, str(HUMAN_TRIALS))

from amongagents.envs.action import Speak
from amongagents.envs.configs.game_config import FIVE_MEMBER_GAME
from amongagents.envs.game import AmongUs
from db import _db_file, init_db
from models import WebPlayerAgent
from server_helpers import log_human_action, record_engine_action, record_system_event


def test_engine_speech_creates_event_and_discussion_message(monkeypatch, tmp_path):
    monkeypatch.setenv("EXPERIMENT_PATH", str(tmp_path))
    init_db()
    game = AmongUs(
        game_config=FIVE_MEMBER_GAME,
        agent_config={
            "Impostor": "LLM",
            "Crewmate": "LLM",
            "IMPOSTOR_LLM_CHOICES": ["gemini/test-model"],
            "CREWMATE_LLM_CHOICES": ["gemini/test-model"],
        },
        game_index="web_test_game",
    )
    game.game_id = "web_test_game"
    game.meeting_number = 1
    game.record_game_action = record_engine_action
    game.record_game_system_event = record_system_event
    game.initialize_game()
    game.agents[0] = WebPlayerAgent(game.players[0])
    game.current_phase = "meeting"

    action = Speak(game.players[0].location)
    action.provide_message("I saw nothing suspicious.")
    log_human_action(
        game,
        game.players[0],
        "SPEAK",
        {"message": "I saw nothing suspicious.", "phase": "meeting"},
    )
    game.record_activity(game.players[0], action)
    log_human_action(game, game.players[0], "VOTE", {"target": "none"})

    conn = sqlite3.connect(_db_file())
    event = conn.execute(
        "SELECT event_type, actor_role, state_snapshot FROM game_events WHERE event_type = 'SPEAK'"
    ).fetchone()
    message = conn.execute(
        "SELECT meeting_number, message_text FROM discussion_messages"
    ).fetchone()
    submission = conn.execute(
        """
        SELECT id, event_type, event_status, actor_name, actor_type, actor_role, location, action_name
        FROM game_events
        WHERE event_type = 'ACTION_SUBMITTED' AND action_name = 'SPEAK'
        """
    ).fetchone()
    executed_speech_id = conn.execute(
        "SELECT id FROM game_events WHERE event_type = 'SPEAK'"
    ).fetchone()[0]
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()

    assert event[0] == "SPEAK"
    assert event[1] in {"Crewmate", "Impostor"}
    assert '"players"' in event[2]
    assert message == (1, "I saw nothing suspicious.")
    assert submission == (
        1,
        "ACTION_SUBMITTED",
        "submitted",
        game.players[0].name,
        "human",
        game.players[0].identity,
        game.players[0].location,
        "SPEAK",
    )
    assert submission[0] < executed_speech_id
    assert {"games", "game_players", "game_events", "discussion_messages", "llm_interactions"} <= tables
    assert not {"human_actions", "agent_interactions", "game_outcomes"} & tables
