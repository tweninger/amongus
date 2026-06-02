# AmongUs Server Deployment

The production service should run the same ASGI target used for local
development:

```bash
uvicorn amongus_server.main:app --host 127.0.0.1 --port 8011
```

## Local Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -e ./among-agents
pip install -e ".[dev]"
uvicorn amongus_server.main:app --host 127.0.0.1 --port 8011 --reload
```

Open `http://127.0.0.1:8011`.

## dsg7 systemd

Use the repo root as the working directory and install both packages into the
virtualenv. The service no longer needs a custom `PYTHONPATH`.

```ini
[Unit]
Description=AmongUs FastAPI app
After=network.target

[Service]
User=mbai
Group=campus
WorkingDirectory=/home/mbai/amongus

Environment="PATH=/home/mbai/amongus/venv/bin:/usr/local/bin:/usr/bin:/bin"
EnvironmentFile=/home/mbai/amongus/.env

ExecStart=/home/mbai/amongus/venv/bin/uvicorn amongus_server.main:app --host 127.0.0.1 --port 8011
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

## Apache

The existing Apache proxy shape is correct. Keep the WebSocket route before the
catch-all `/` proxy:

```apache
ProxyPass /ws ws://127.0.0.1:8011/ws
ProxyPassReverse /ws ws://127.0.0.1:8011/ws

ProxyPass / http://127.0.0.1:8011/
ProxyPassReverse / http://127.0.0.1:8011/
```

