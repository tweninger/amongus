# Legacy Human Trials Entrypoints

These files are retained for historical reference only. They predate the
current FastAPI/ASGI server path and may depend on imports or requirements that
are not installed by default.

The active server remains in `human_trials/server.py` and is imported through:

```text
amongus_server.main:app
```
