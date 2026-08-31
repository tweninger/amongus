import json
import os
import sqlite3
from pathlib import Path

# db.py: Handles SQLite database interactions for human and agent logs

HUMAN_TRIALS_DIR = Path(__file__).resolve().parent
DEFAULT_LOG_DIR = HUMAN_TRIALS_DIR / "logs"


def _experiment_path() -> Path:
    experiment_path = Path(os.environ.get("EXPERIMENT_PATH", DEFAULT_LOG_DIR)).expanduser()
    experiment_path.mkdir(parents=True, exist_ok=True)
    return experiment_path

def _db_file():
    # Resolves to logs/game_data.db alongside the existing JSON log files
    return _experiment_path() / "game_data.db"

def init_db():
    # Version 2 intentionally replaces the earlier three-table event dump.
    # JSON runtime logs are retained separately, but this SQLite file becomes the
    # authoritative analysis dataset.
    conn = sqlite3.connect(_db_file())
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    schema_version = conn.execute(
        "SELECT value FROM schema_metadata WHERE key = 'schema_version'"
    ).fetchone()
    if schema_version is None or schema_version[0] != "2":
        conn.executescript("""
            DROP TABLE IF EXISTS human_actions;
            DROP TABLE IF EXISTS agent_interactions;
            DROP TABLE IF EXISTS game_outcomes;
        """)
        conn.execute(
            """
            INSERT INTO schema_metadata (key, value) VALUES ('schema_version', '2')
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """
        )
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS games (
            game_id TEXT PRIMARY KEY,
            room_code TEXT,
            server_session_id TEXT,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            game_config TEXT NOT NULL,
            runtime_config TEXT NOT NULL,
            code_revision TEXT,
            winner TEXT,
            win_condition TEXT,
            total_steps INTEGER
        );
        CREATE TABLE IF NOT EXISTS game_players (
            game_id TEXT NOT NULL,
            player_slot INTEGER NOT NULL,
            player_name TEXT NOT NULL,
            player_color TEXT,
            participant_type TEXT NOT NULL,
            role TEXT NOT NULL,
            model TEXT,
            personality TEXT,
            consented_at TEXT,
            joined_at TEXT,
            disconnected_at TEXT,
            final_is_alive INTEGER,
            final_is_connected INTEGER,
            PRIMARY KEY (game_id, player_slot),
            FOREIGN KEY (game_id) REFERENCES games(game_id)
        );
        CREATE TABLE IF NOT EXISTS game_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            timestep INTEGER,
            phase TEXT,
            meeting_number INTEGER NOT NULL DEFAULT 0,
            event_type TEXT NOT NULL,
            event_status TEXT NOT NULL,
            actor_slot INTEGER,
            actor_name TEXT,
            actor_type TEXT,
            actor_role TEXT,
            target_slot INTEGER,
            target_name TEXT,
            location TEXT,
            action_name TEXT,
            payload TEXT NOT NULL,
            state_snapshot TEXT NOT NULL,
            FOREIGN KEY (game_id) REFERENCES games(game_id)
        );
        CREATE TABLE IF NOT EXISTS discussion_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id TEXT NOT NULL,
            event_id INTEGER,
            occurred_at TEXT NOT NULL,
            timestep INTEGER,
            meeting_number INTEGER NOT NULL,
            speaker_slot INTEGER,
            speaker_name TEXT NOT NULL,
            speaker_type TEXT NOT NULL,
            speaker_role TEXT NOT NULL,
            speaker_model TEXT,
            message_text TEXT NOT NULL,
            payload TEXT NOT NULL,
            FOREIGN KEY (game_id) REFERENCES games(game_id),
            FOREIGN KEY (event_id) REFERENCES game_events(id)
        );
        CREATE TABLE IF NOT EXISTS llm_interactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            timestep INTEGER,
            player_name TEXT NOT NULL,
            player_role TEXT NOT NULL,
            player_personality TEXT,
            player_model TEXT NOT NULL,
            player_location TEXT,
            system_prompt TEXT,
            prompt TEXT NOT NULL,
            response TEXT NOT NULL,
            full_response TEXT NOT NULL,
            FOREIGN KEY (game_id) REFERENCES games(game_id)
        );
        CREATE INDEX IF NOT EXISTS idx_game_events_game_time
            ON game_events(game_id, occurred_at, id);
        CREATE INDEX IF NOT EXISTS idx_game_events_game_type
            ON game_events(game_id, event_type);
        CREATE INDEX IF NOT EXISTS idx_discussion_messages_game_time
            ON discussion_messages(game_id, occurred_at, id);
        CREATE INDEX IF NOT EXISTS idx_llm_interactions_game_time
            ON llm_interactions(game_id, occurred_at, id);
    """)
    conn.commit()
    conn.close()


def _json(value) -> str:
    return json.dumps(value, default=str, sort_keys=True)


def insert_game(record: dict):
    conn = sqlite3.connect(_db_file())
    conn.execute(
        """
        INSERT INTO games (
            game_id, room_code, server_session_id, started_at, game_config,
            runtime_config, code_revision
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(game_id) DO NOTHING
        """,
        (
            record["game_id"], record.get("room_code"), record.get("server_session_id"),
            record["started_at"], _json(record.get("game_config", {})),
            _json(record.get("runtime_config", {})), record.get("code_revision"),
        ),
    )
    conn.commit()
    conn.close()


def upsert_game_players(records: list[dict]):
    if not records:
        return
    conn = sqlite3.connect(_db_file())
    conn.executemany(
        """
        INSERT INTO game_players (
            game_id, player_slot, player_name, player_color, participant_type,
            role, model, personality, consented_at, joined_at, disconnected_at,
            final_is_alive, final_is_connected
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(game_id, player_slot) DO UPDATE SET
            player_name = excluded.player_name,
            player_color = excluded.player_color,
            participant_type = excluded.participant_type,
            role = excluded.role,
            model = excluded.model,
            personality = excluded.personality,
            consented_at = COALESCE(excluded.consented_at, game_players.consented_at),
            joined_at = COALESCE(excluded.joined_at, game_players.joined_at),
            disconnected_at = COALESCE(excluded.disconnected_at, game_players.disconnected_at),
            final_is_alive = COALESCE(excluded.final_is_alive, game_players.final_is_alive),
            final_is_connected = COALESCE(excluded.final_is_connected, game_players.final_is_connected)
        """,
        [
            (
                record["game_id"], record["player_slot"], record["player_name"],
                record.get("player_color"), record["participant_type"], record["role"],
                record.get("model"), record.get("personality"), record.get("consented_at"),
                record.get("joined_at"), record.get("disconnected_at"),
                record.get("final_is_alive"), record.get("final_is_connected"),
            )
            for record in records
        ],
    )
    conn.commit()
    conn.close()


def insert_game_event(record: dict) -> int:
    conn = sqlite3.connect(_db_file())
    cursor = conn.execute(
        """
        INSERT INTO game_events (
            game_id, occurred_at, timestep, phase, meeting_number, event_type,
            event_status, actor_slot, actor_name, actor_type, actor_role,
            target_slot, target_name, location, action_name, payload, state_snapshot
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record["game_id"], record["occurred_at"], record.get("timestep"),
            record.get("phase"), record.get("meeting_number", 0), record["event_type"],
            record.get("event_status", "executed"), record.get("actor_slot"),
            record.get("actor_name"), record.get("actor_type"), record.get("actor_role"),
            record.get("target_slot"), record.get("target_name"), record.get("location"),
            record.get("action_name"), _json(record.get("payload", {})),
            _json(record.get("state_snapshot", {})),
        ),
    )
    conn.commit()
    event_id = cursor.lastrowid
    conn.close()
    return event_id


def insert_discussion_message(record: dict):
    conn = sqlite3.connect(_db_file())
    conn.execute(
        """
        INSERT INTO discussion_messages (
            game_id, event_id, occurred_at, timestep, meeting_number, speaker_slot,
            speaker_name, speaker_type, speaker_role, speaker_model, message_text, payload
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record["game_id"], record.get("event_id"), record["occurred_at"],
            record.get("timestep"), record.get("meeting_number", 0),
            record.get("speaker_slot"), record["speaker_name"], record["speaker_type"],
            record["speaker_role"], record.get("speaker_model"), record["message_text"],
            _json(record.get("payload", {})),
        ),
    )
    conn.commit()
    conn.close()


def finish_game(record: dict):
    conn = sqlite3.connect(_db_file())
    conn.execute(
        """
        UPDATE games
        SET ended_at = ?, winner = ?, win_condition = ?, total_steps = ?
        WHERE game_id = ?
        """,
        (
            record["ended_at"], record.get("winner"), record.get("win_condition"),
            record.get("total_steps"), record["game_id"],
        ),
    )
    conn.commit()
    conn.close()


def insert_llm_interaction(record: dict):
    conn = sqlite3.connect(_db_file())
    conn.execute(
        """
        INSERT INTO llm_interactions (
            game_id, occurred_at, timestep, player_name, player_role,
            player_personality, player_model, player_location, system_prompt,
            prompt, response, full_response
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record["game_id"], record["occurred_at"], record.get("timestep"),
            record["player_name"], record["player_role"], record.get("player_personality"),
            record["player_model"], record.get("player_location"),
            record.get("system_prompt"), _json(record.get("prompt", {})),
            _json(record.get("response", {})), record.get("full_response", ""),
        ),
    )
    conn.commit()
    conn.close()
