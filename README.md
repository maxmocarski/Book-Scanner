# BookBridge

Photograph physical books, build a private library, and arrange swaps with friends. Inspired by [ReVolt](https://github.com/maxmocarski/Revolt), with a separate app, database, and web interface.

BookBridge runs a FastAPI backend and a simple HTML/CSS/JavaScript frontend. Book recognition uses Gemma through your own Ollama server; SearXNG lookup is optional.

## What it does

- Scan one book with up to three photos: front, spine, and back.
- Queue books while another scans; the queue survives restarts.
- Review title, author, ISBN and text corrections before saving.
- Search/edit your library and choose which books are available to trade.
- Invite friends, browse their libraries, and request book-for-book swaps.
- Transfer ownership and photos after both people confirm the physical exchange.

## Run locally

Use Linux/WSL and Python 3.12. Install Ollama separately and download the models:

```bash
ollama pull gemma3:12b
ollama pull gemma3:1b

git clone https://github.com/maxmocarski/Book-Scanner.git
cd Book-Scanner
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
OLLAMA_HOST=http://127.0.0.1:11434 .venv/bin/uvicorn main:app --host 127.0.0.1 --port 8503
```

Open **http://localhost:8503/** for the app; `/docs` provides developer API controls. Sign up, scan, review and save. Use one worker: the queue and migration lock prevent multiple processes sharing the same data directory.

The primary model must support images. The default `gemma3:1b` second pass only handles text. A cold model or CPU inference can take longer; models are unloaded after each pass by default to reduce memory pressure.

## Docker with existing Ollama

The supplied Compose file expects existing `ollama` and optionally `searxng` containers on a shared Docker network. It does **not** create those services.

```bash
cp .env.example .env
# Edit BOOKBRIDGE_NETWORK to your existing Docker network name.
docker compose up -d --build
```

The example defaults to `revolt_default`. Ollama must be reachable as `http://ollama:11434` on that network; adjust `OLLAMA_HOST` in Compose if its service name differs. BookBridge listens on localhost port 8503 and stores its data in a named volume.

For an existing installation managed by another stack, keep that stack's Compose service and data mount. Update only this app's code and rebuild its service; don't switch data volumes accidentally.

### Existing guzdekai installation

BookBridge's source is `~/bookbridge`; the active Compose file is `~/revolt/docker-compose.yml` with `build: ../bookbridge` and `../bookbridge/data:/data`.

```bash
cd ~/bookbridge
git pull
cd ~/revolt
sudo docker compose up -d --build --no-deps bookbridge
```

This rebuilds BookBridge separately from ReVolt. The repository cleanup does not change the database schema, API paths, container port or mounted data.

## Phone access and privacy

Camera capture requires HTTPS or localhost. Use your own private HTTPS proxy, such as Tailscale Serve, for a phone. You can upload photos when live camera access is unavailable. Desktop users can use an SSH localhost tunnel.

Accounts and book photos are private; accepted friends can see each other's entire collections. Invitation codes are single-use and expire after 24 hours. The backend sends no email or other messages. Lookup mode sends title/author or ISBN queries through SearXNG; photos stay with your Ollama server.

Public hosting needs additional controls. Registration is currently open, and there are no public-facing rate limits, account recovery or total storage quotas. A public link permits strangers to register and submit scans. Model output, ISBN checksums and search snippets do not guarantee the correct edition: review before saving.

## Project layout

| Path | Purpose |
|---|---|
| `main.py` | API, frontend serving, accounts, library and trades |
| `scanning.py` | Persistent queue, image processing and AI/search passes |
| `schema.py` | SQLite tables and migration |
| `static/` | Web interface, styles, JavaScript and icon |
| `tests/` | Backend regressions and disposable browser checks |
| `docs/REFERENCE.md` | Configuration, ISBN safeguards and data migration |
| `docs/ROADMAP.md` | Ideas for future improvements |
| `Dockerfile`, `compose.yaml` | Container deployment |
| `.env.example` | Example configuration; copy to private `.env` |

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

Browser checks use a temporary database and fake model/search responses. **Do not run them against your real library.**

```bash
# Terminal 1
.venv/bin/python tests/ui/mock_server.py

# Terminal 2 (development dependencies only)
npm install --no-save playwright
npx playwright install chromium
node tests/ui/run.cjs
```

No JavaScript build step or Node dependency is required to run the actual app. AI/browser tests use mocked inference and do not measure live recognition quality.
