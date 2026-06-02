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
    # Creates both tables on first run
    conn = sqlite3.connect(_db_file())
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS human_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_index TEXT,
            step INTEGER,
            timestamp TEXT,
            player_name TEXT,
            player_identity TEXT,
            player_location TEXT,
            action_type TEXT,
            action_payload TEXT
        );
        CREATE TABLE IF NOT EXISTS agent_interactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_index TEXT,
            step INTEGER,
            timestamp TEXT,
            player_name TEXT,
            player_identity TEXT,
            player_personality TEXT,
            player_model TEXT,
            player_location TEXT,
            system_prompt TEXT,
            prompt TEXT,
            response TEXT,
            full_response TEXT
        );
        CREATE TABLE IF NOT EXISTS game_outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_index TEXT,
            timestamp TEXT,
            winner TEXT,
            win_condition TEXT,
            total_steps INTEGER,
            players TEXT
        );
    """)
    conn.commit()
    conn.close()

# entry is a dict matching the structure of a single log entry in human-logs.json
def insert_human_action(entry: dict):
    # Mirrors human-logs.json entry structure.
    action = entry.get("action", {})
    payload = {k: v for k, v in action.items() if k != "type"}
    try:
        conn = sqlite3.connect(_db_file())
        # Insert relevant fields, converting into json to preserve structure
        conn.execute(
            "INSERT INTO human_actions VALUES (NULL,?,?,?,?,?,?,?,?)",
            (
                entry.get("game_index"),
                entry.get("step"),
                entry.get("timestamp"),
                entry["player"]["name"],
                entry["player"]["identity"],
                entry["player"]["location"],
                action.get("type"),
                json.dumps(payload),
            ),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[DB] human_actions insert error: {e}")

def insert_game_outcome(entry: dict):
    try:
        conn = sqlite3.connect(_db_file())
        conn.execute(
            "INSERT INTO game_outcomes VALUES (NULL,?,?,?,?,?,?)",
            (
                entry.get("game_index"),
                entry.get("timestamp"),
                entry.get("winner"),
                entry.get("win_condition"),
                entry.get("total_steps"),
                json.dumps(entry.get("players", [])),
            ),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[DB] game_outcomes insert error: {e}")

def insert_agent_interaction(interaction: dict):
    # Mirrors agent-logs.json entry structure.
    player = interaction.get("player", {})
    interaction = interaction.get("interaction", {})
    try:
        conn = sqlite3.connect(_db_file())
        conn.execute(
            "INSERT INTO agent_interactions VALUES (NULL,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                interaction.get("game_index"),
                interaction.get("step"),
                interaction.get("timestamp"),
                player.get("name"),
                player.get("identity"),
                player.get("personality"),
                player.get("model"),
                player.get("location"),
                interaction.get("system_prompt"),
                json.dumps(interaction.get("prompt")),
                json.dumps(interaction.get("response")),
                interaction.get("full_response") if isinstance(interaction.get("full_response"), str) else json.dumps(interaction.get("full_response")),
            ),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[DB] agent_interactions insert error: {e}")
