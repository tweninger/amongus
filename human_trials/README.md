# Human Trials Server

This directory contains the active FastAPI game server implementation and its
browser assets.

The Python project is configured at the repository root in `pyproject.toml`.
Install and run the app from the repo root:

```bash
make install-dev
make run
```

The stable ASGI target is:

```text
amongus_server.main:app
```

See the root `README.md` for local development and `DEPLOYMENT.md` for the
`dsg7` Apache/systemd setup.
