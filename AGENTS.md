# xdcterm

Terminal emulator delivered as a Delta Chat WebXDC app.

## Structure

```
frontend/   — vanilla JS + xterm.js, built with Vite
backend/    — Python Delta Chat bot using deltabot-cli
```

## Commands

| Directory | Command | Purpose |
|-----------|---------|---------|
| `frontend/` | `npm install` then `npm run build` | Build → `frontend/dist-release/xdcterm.xdc` |
| `frontend/` | `npm run dev` | Vite dev server with HMR |
| `backend/`  | `uv sync` | Install Python deps |
| `backend/`  | `uv run bot.py init DCACCOUNT:nine.testrun.org` | Init DC account |
| `backend/`  | `uv run bot.py serve` | Start the bot |

**Build order matters:** run `npm run build` in `frontend/` first — `bot.py` reads `frontend/dist-release/xdcterm.xdc` at line 23.

## Setup

- Frontend uses **npm** (not pnpm/yarn). Backend uses **uv** (not pip).
- Python pinned to **3.13** (`backend/.python-version`), requires `>=3.13`.
- No TypeScript — frontend is plain JS. No tsconfig.json.
- **No test framework, no linter, no typechecker, no CI, no pre-commit hooks** exist.
- `webxdc.js` is not an npm package — loaded at runtime by the WebXDC host.

## Backend

- **Entrypoint:** `backend/bot.py` → `cli.start()` (deltabot-cli CLI).
- **Database:** SQLite at `backend/data/xdcterm.db` (WAL mode, thread-safe via `threading.Lock`). No migration system — `CREATE TABLE IF NOT EXISTS` only.
- **PTY lifecycle:** one PTY per WebXDC msg id, 60s idle timeout, auto-closed on instance delete.
- **Bot commands:** `/start` (sends WebXDC app), `/list` (active sessions).
- **First user** auto-assigned as admin (receives PTY open/close notifications).
- **Environment:** `$SHELL` for PTY child (defaults to `bash`); `$HOSTNAME` fallback for bot display name.
- **Systemd user service:** `xdcterm.service` at repo root. Type simple, restart on-failure, working dir `backend/`.

## Frontend

- **xterm.js** with FitAddon + ImageAddon (sixel support).
- Custom font: JetBrains Mono Nerd Font (`jetbrains-mono-nf.woff2`).
- Uses Delta Chat WebXDC realtime API (`window.webxdc.joinRealtimeChannel()`).
- Build produces `.xdc` file via `vite-plugin-zip-pack`.
- Heartbeat sends LIFECYCLE_OPEN every 1s while visible; LIFECYCLE_CLOSE on hide/pagehide.

## Protocol (binary over WebXDC realtime)

Defined identically in `frontend/protocol.js` and `backend/bot.py`:

| Byte | Command   | Payload                                           |
|------|-----------|---------------------------------------------------|
| `0x49` | INPUT    | UTF-8 keyboard input → PTY                        |
| `0x4f` | OUTPUT   | PTY stdout → terminal                             |
| `0x45` | EXIT     | (none) PTY finished                               |
| `0x52` | RESIZE   | 4 bytes: cols hi/lo, rows hi/lo                   |
| `0x43` | LIFECYCLE| 1 byte: `0x01`=open, `0x00`=close                |
