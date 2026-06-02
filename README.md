# AmongUs Server

This repository contains the human-trials FastAPI game server and the
`among-agents` game engine package it depends on.

## Local Development

```bash
python -m venv venv
source venv/bin/activate
pip install -e ./among-agents
pip install -e ".[dev]"
uvicorn amongus_server.main:app --host 127.0.0.1 --port 8011 --reload
```

Open `http://127.0.0.1:8011`.

The stable ASGI app import is:

```text
amongus_server.main:app
```

See `DEPLOYMENT.md` for the dsg7 Apache/systemd shape.

