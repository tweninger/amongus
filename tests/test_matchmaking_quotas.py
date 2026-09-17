import asyncio
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "human_trials"))

import server  # noqa: E402
from db import _db_file, completed_matchmaking_counts, init_db  # noqa: E402


def test_quota_counts_completed_original_rosters_since_eastern_midnight(monkeypatch, tmp_path):
    monkeypatch.setenv("EXPERIMENT_PATH", str(tmp_path))
    init_db()
    with sqlite3.connect(_db_file()) as conn:
        for name, started, winner, humans, size in [
            ("before", "2026-09-07T03:59:59+00:00", "Crewmates", 5, 5),
            ("boundary", "2026-09-07T04:00:00+00:00", "Crewmates", 5, 5),
            ("mixed", "2026-09-08T00:00:00+00:00", "Impostors", 2, 5),
            ("unfinished", "2026-09-08T00:00:00+00:00", None, 2, 5),
            ("other_size", "2026-09-08T00:00:00+00:00", "Crewmates", 2, 4),
        ]:
            conn.execute(
                "INSERT INTO games (game_id, started_at, winner, game_config, runtime_config) VALUES (?, ?, ?, '{}', '{}')",
                (name, started, winner),
            )
            for slot in range(size):
                conn.execute(
                    "INSERT INTO game_players (game_id, player_slot, player_name, participant_type, role, disconnected_at) "
                    "VALUES (?, ?, ?, ?, 'Crewmate', '2026-09-08T01:00:00+00:00')",
                    (name, slot, str(slot), "human" if slot < humans else "ai"),
                )
    assert completed_matchmaking_counts("2026-09-07T00:00:00-04:00") == {1: 0, 2: 1, 3: 0, 4: 0, 5: 1}


def test_full_quotas_restore_normal_matchmaking(monkeypatch):
    monkeypatch.setattr(server, "MATCHMAKING_QUOTA_PER_CONFIGURATION", 100)
    monkeypatch.setattr(server, "completed_matchmaking_counts", lambda _: dict.fromkeys(range(1, 6), 100))
    assert server.eligible_human_counts(5) == {1, 2, 3, 4, 5}


def test_quota_admission_and_ai_fill(monkeypatch):
    monkeypatch.setattr(server, "MATCHMAKING_QUOTA_PER_CONFIGURATION", 100)
    counts = {1: 100, 2: 100, 3: 99, 4: 99, 5: 100}
    monkeypatch.setattr(server, "completed_matchmaking_counts", lambda _: counts)
    room = SimpleNamespace(total_slots=5, quota_human_target=4, sessions={"a": 0, "b": 1}, ai_filled_slots=set(),
                           game_instance=SimpleNamespace(agents=[object() for _ in range(5)]))
    assert server.get_next_open_slot(room) == 2
    room.sessions["c"] = 2
    room.sessions["d"] = 3
    assert server.get_next_open_slot(room) is None
    counts[4] = 100
    assert room.quota_human_target == 4  # Existing roster stays fixed as quotas change.


def test_quota_disabled_and_other_room_sizes(monkeypatch):
    monkeypatch.setattr(server, "MATCHMAKING_QUOTA_PER_CONFIGURATION", 0)
    assert server.eligible_human_counts(5) == {1, 2, 3, 4, 5}
    assert server.eligible_human_counts(3) == {1, 2, 3}


@pytest.mark.parametrize("largest_needed", [1, 2, 3, 4, 5])
def test_required_ai_are_visible_immediately_and_preserved(monkeypatch, largest_needed):
    monkeypatch.setattr(server, "eligible_human_counts", lambda _: set(range(1, largest_needed + 1)))
    room = SimpleNamespace(total_slots=5, sessions={"host": 0}, ai_filled_slots=set())
    server.fill_required_quota_ai(room)
    assert len(room.ai_filled_slots) == 5 - largest_needed
    assert 0 not in room.ai_filled_slots
    assert len(server.get_open_slots(room)) == largest_needed - 1
    original_slots = room.ai_filled_slots.copy()
    server.fill_required_quota_ai(room)
    assert room.ai_filled_slots == original_slots


def test_quota_lobby_still_starts_visible_ai_countdown(monkeypatch):
    async def check():
        room = SimpleNamespace(status="open", quota_human_target=3, lobby_deadline=0,
                               lobby_fill_task=None, sessions={"host": 0},
                               consented_tokens={"host"})
        called = []

        async def countdown(candidate):
            called.append(candidate)

        monkeypatch.setattr(server.time, "time", lambda: 100)
        monkeypatch.setattr(server, "run_lobby_countdown", countdown)
        server.start_lobby_countdown_if_ready(room)
        await room.lobby_fill_task
        assert called == [room]
        assert room.lobby_deadline == 100 + server.LOBBY_COUNTDOWN_SECONDS
        assert server.get_lobby_seconds_left(room) == server.LOBBY_COUNTDOWN_SECONDS

    asyncio.run(check())
