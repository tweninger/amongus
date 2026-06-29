import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AMONG_AGENTS = ROOT / "among-agents"

if str(AMONG_AGENTS) not in sys.path:
    sys.path.insert(0, str(AMONG_AGENTS))
