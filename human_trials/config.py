import uuid
import datetime
import subprocess

# Generate unique session ID
SESSION_ID = str(uuid.uuid4())[:8]

# Get experiment date and Git commit hash
DATE = datetime.datetime.now().strftime("%Y-%m-%d")
COMMIT_HASH = (
    subprocess.check_output(["git", "rev-parse", "HEAD"]).strip().decode("utf-8")
)

# Configuration dictionary
CONFIG = {
    "session_id": SESSION_ID,
    "date": DATE,
    "commit_hash": COMMIT_HASH,
    "game_args": {
        "game_config": "FIVE_MEMBER_GAME",
        "include_human": False,
        "test": False,
        "personality": False,
        "agent_config": {
            "Impostor": "LLM", 
            "Crewmate": "LLM",    
            "IMPOSTOR_LLM_CHOICES": ["meta-llama/llama-3.3-70b-instruct"],
            "CREWMATE_LLM_CHOICES": ["meta-llama/llama-3.3-70b-instruct"],
        },
        "UI": False,
    },
    "experiment_name": f"session_{SESSION_ID}",
    "logs_path": "expt-logs",
    "assets_path": "assets",
}

