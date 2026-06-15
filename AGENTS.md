## Architecture

- **`frontend/`** — standalone Vite + xterm.js WebXDC app. Build once: `cd frontend && npm install && npm run build`. Produces `frontend/dist-release/xdcterm.xdc`. Not touched by bot work.
- **`backend/`** — Python bot using `deltabot-cli`. Managed with `uv`.

## Build & run

```sh
cd frontend && npm install && npm run build   # frontend .xdc
cd backend && uv sync                          # bot deps
uv run bot.py init DCACCOUNT:nine.testrun.org  # first-time account setup
uv run bot.py serve                            # start bot
```

## backends/bot.py

Uses `BotCli("xdcterm")` from `deltabot-cli`. Event handlers registered via `@cli.on(events.RawEvent(...))` filters — no if-else chains:

| Handler | Filter | Purpose |
|---|---|---|
| `on_start` | `@cli.on_start` | (placeholder — built-in serve prints QR) |
| `on_securejoin` | `RawEvent(types=[EventType.SECUREJOIN_INVITER_PROGRESS])` | Securejoin complete → send WebXDC |
| `on_start_cmd` | `NewMessage(command="/start")` | User sends /start → send WebXDC |
| `on_webxdc_data` | `RawEvent(func=lambda e: e.kind == "WebxdcRealtimeData")` | Forward terminal input to PTY |
| `on_ad_received` | `RawEvent(func=lambda e: e.kind == ...)` | Multi-device: spawn PTY for each joiner |
| `on_instance_deleted` | `RawEvent(func=lambda e: e.kind == ...)` | Clean up PTY on WebXDC close |

Event kinds not in `deltachat2.EventType` enum are matched as raw strings via `func=lambda`.

## Protocol (backed ↔ frontend)

Binary over WebXDC realtime channel:
- `0x49` ('I') — input from frontend → PTY stdin
- `0x4f` ('O') — output from PTY → frontend
- `0x45` ('E') — PTY exit signal → frontend
- `0x52` ('R') — resize terminal (4 bytes big-endian: cols, rows)

## PTY

Python `pty.fork()` + daemon thread per PTY reading the master fd. `IOTransport` is thread-safe (all JSON-RPC writes go through a single queue-based writer thread), so PTY reader threads call `send_webxdc_realtime_data()` directly.

## Notable

- No tests, no CI, no typechecking.
- No Node.js files at root — frontend is the only npm project.
- `nine.testrun.org` for disposable test accounts.
- `deltachat-rpc-server` binary auto-downloaded by `deltachat2[full]` via `pip`/`uv`.
- No `.nvmrc` — Python 3.10+ only (`backend/.python-version`).
