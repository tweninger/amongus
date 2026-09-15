# AmongUs Server

This repository contains the human-trials FastAPI game server and the
`among-agents` game engine package it depends on.

## Local Development

```bash
python -m venv venv
source venv/bin/activate
make install-dev
make install-browser
make run
```

Open `http://127.0.0.1:8011`.

## LLM Provider

The server calls model providers directly. Configure one provider in `.env`:

```bash
LLM_PROVIDER=gemini  # openai, gemini, or anthropic
LLM_MODEL=gemini-3.5-flash
GEMINI_API_KEY=...
```

Use `OPENAI_API_KEY`, `GEMINI_API_KEY`, or `ANTHROPIC_API_KEY` for the selected
provider. Optional role-specific overrides are also supported:
`CREWMATE_LLM_MODEL`, `IMPOSTOR_LLM_MODEL`, `CREWMATE_LLM_MODELS`, and
`IMPOSTOR_LLM_MODELS`.

For headless browser checks, Playwright may require OS packages. Check them with:

```bash
make check-browser-deps
```

If packages are missing, run this manually in an interactive terminal so sudo can
prompt:

```bash
venv/bin/python -m playwright install-deps chromium
```

Then run:

```bash
make check-matchmaking
```

The stable ASGI app import is:

```text
amongus_server.main:app
```

See `DEPLOYMENT.md` for the dsg7 Apache/systemd shape.

## Matchmaking Quotas

Five-player matchmaking targets 100 completed games of each composition, from
one human/four AI through five humans/no AI. Configure these settings in `.env`
and restart the server:

```dotenv
MATCHMAKING_QUOTA_PER_CONFIGURATION=100
MATCHMAKING_QUOTA_START_DATE=2026-09-07
```

The cutoff includes midnight on that date in America/New_York. Counts use the
original roster and a recorded Crewmates or Impostors winner in the live
`EXPERIMENT_PATH/game_data.db` (default: `human_trials/logs/game_data.db`).
Database snapshots elsewhere in the repository are not included automatically.

Lobbies admit up to the largest human count still needed. Further arrivals enter
another lobby. The usual countdown fills AI seats only for an eligible human
count; otherwise the lobby waits for more humans. If a quota fills while a lobby
is waiting and no larger eligible composition can accommodate its players, that
existing roster may start anyway. Concurrent games can slightly exceed targets.

Once all five targets are met, normal matchmaking resumes automatically. Set the
target to 0 to disable quotas. Other game sizes are unaffected.

Check current quotas from the command line using the same `.env` settings:

```bash
venv/bin/python scripts/show_quotas.py
```

To inspect a saved database instead, add `--db first100.db`. The report only
reads the database and does not start the server or change any records.
