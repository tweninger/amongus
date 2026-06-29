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
