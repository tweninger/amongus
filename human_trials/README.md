# Human Trials Server

This directory contains the active FastAPI game server implementation and its
browser assets.

The Python project is configured at the repository root in `pyproject.toml`.
Install and run the app from the repo root:

```bash
pip install -e ./among-agents
pip install -e ".[dev]"
uvicorn amongus_server.main:app --host 127.0.0.1 --port 8011 --reload
```

The stable ASGI target is:

```text
amongus_server.main:app
```

See the root `README.md` for local development and `DEPLOYMENT.md` for the
`dsg7` Apache/systemd setup.
