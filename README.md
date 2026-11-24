# BookBridge

BookBridge is a self-hosted app for cataloging physical books. Photograph a single book or a shelf, review the results, and organize your collection from a phone or desktop.

BookBridge runs on FastAPI, SQLite, and a plain HTML, CSS, and JavaScript frontend. It uses Ollama for local book recognition and can use SearXNG for metadata and cover searches.

## What you can do

- Scan a book using cover, spine, or back photos, or scan multiple books from a shelf photo. The scan queue persists across restarts.
- Review and edit titles, authors, ISBNs, and genres before saving. ISBNs are optional. Check any lookup suggestions against your copy.
- Browse your collection as covers, shelves, or a list. Organize books by genre or shelf and export selected books or a shared library to CSV.
- Request a cover search in the background, then review the suggested image. BookBridge keeps the original scan.
- Share libraries with invited members, opt in to a public catalog, or arrange book swaps with friends. Ownership transfers after both people confirm the exchange.

## Test it yourself

https://guzdekai.tailf6698c.ts.net:8443/

## Run locally

Use Python 3.12 on Linux or WSL. Start Ollama and download the default vision and text models:

```bash
ollama pull gemma3:12b
ollama pull gemma3:1b
```

```bash
git clone https://github.com/maxmocarski/Book-Scanner.git
cd Book-Scanner
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn api.main:app --host 127.0.0.1 --port 8503
```

Open [BookBridge](http://localhost:8503/) to create an account and scan a book. The [API docs](http://localhost:8503/docs) are also available. Run one BookBridge process per data directory so a single worker owns the scan queue.

Phone camera capture requires HTTPS. Serve BookBridge through a private HTTPS proxy, such as Tailscale Serve, or upload existing photos from your device.

## Run with Docker Compose

The included [compose.yaml](compose.yaml) starts BookBridge. Use an existing Docker network with Ollama reachable as `ollama:11434`. For search features, SearXNG must be reachable as `searxng:8080`. If your containers use other hostnames, set the corresponding URLs in the Compose service.

Set the network in a `.env` file beside `compose.yaml`. The default is `revolt_default`.

```dotenv
BOOKBRIDGE_NETWORK=revolt_default
```

```bash
docker compose up -d --build
docker compose logs --tail=50 bookbridge
```

The app binds to `127.0.0.1:8503` on the Docker host. Compose mounts the `bookbridge-data` volume at `/data`.

### Update an existing installation

Stop BookBridge and back up its entire data directory before upgrading. Rebuild from the active Compose project using the same volume or bind mount. This also applies to installations where BookBridge runs inside another stack.

Run these commands from the directory of the active Compose file. Update the BookBridge source between the backup and the rebuild.

```bash
docker compose stop bookbridge
docker compose cp bookbridge:/data ./bookbridge-data-backup
```

```bash
docker compose up -d --build --no-deps bookbridge
```

BookBridge migrates older v0.1 databases on startup. Restore the pre-upgrade backup before running v0.1 again.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `OLLAMA_HOST` | `http://localhost:11434` locally, `http://ollama:11434` in Compose | Ollama URL |
| `BOOKBRIDGE_MODEL` | `gemma3:12b` | Vision model for book scans |
| `BOOKBRIDGE_TEXT_MODEL` | `gemma3:1b` | Text model for OCR cleanup and enrichment |
| `BOOKBRIDGE_COVER_MODEL` | Uses `BOOKBRIDGE_MODEL` when unset | Vision model for evaluating cover candidates |
| `BOOKBRIDGE_ENRICHMENT` | `cleanup` | Set to `lookup` to add metadata search or `off` to skip the second pass |
| `SEARXNG_URL` | `http://searxng:8080` | Search URL for metadata lookup and cover search |
| `BOOKBRIDGE_KEEP_ALIVE` | `0` | Unload models after inference. Use a duration such as `5m` to keep them loaded longer |
| `BOOKBRIDGE_MODEL_TIMEOUT` | `180` | Timeout in seconds for model requests |
| `BOOKBRIDGE_MAX_PENDING_PER_USER` | `100` | Maximum pending scans per user |
| `BOOKBRIDGE_MAX_PENDING` | `500` | Maximum pending scans overall |
| `BOOKBRIDGE_DATA` | `./data` locally, `/data` in Docker | Directory for persistent SQLite data |

Compose reads the network, model, enrichment, and keep-alive settings from `.env`. To change an app variable that Compose does not pass through, set it in the service's `environment` block.

For search, enable JSON responses in your SearXNG `settings.yml` and restart SearXNG:

```yaml
search:
  formats:
    - html
    - json
```

## Data and privacy

- Shared libraries start private unless you choose to make them public. Anyone who can reach the app can browse public catalogs and see their book photos without signing in.
- Book recognition sends scan photos to your configured Ollama server. Search sends book metadata such as title, author, or ISBN through SearXNG.
- Friend invite codes are single-use and expire after 24 hours. Unsaved scan results and their photos expire 24 hours after processing finishes.
- BookBridge validates ISBN checksums and preserves original OCR text for review. A valid checksum only checks the number's format. Verify the title, author, and edition before saving.

## Development

| Path | Purpose |
| --- | --- |
| [api/](api/) | FastAPI routes, accounts, libraries, and SQLite schema |
| [core/](core/) | Scan queue, OCR, metadata, genres, and cover search |
| [static/](static/) | Web interface |
| [tests/](tests/) | Backend tests and browser checks |

Run the backend tests:

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

For browser checks, start the disposable mock server in one terminal:

```bash
.venv/bin/python tests/ui/mock_server.py
```

In another terminal, install Playwright and run the checks:

```bash
npm install --no-save playwright
npx playwright install chromium
node tests/ui/run.cjs
```

The mock server uses a temporary database and simulated model responses. Node.js is only needed for the browser checks.
