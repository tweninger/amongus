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
