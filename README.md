# BookBridge

Photograph physical books, build a private library, and arrange swaps with friends. Inspired by ReVolt (https://github.com/maxmocarski/Revolt), with a separate app, database, and web interface.

BookBridge runs a FastAPI backend and a simple HTML/CSS/JavaScript frontend. Book recognition uses Gemma through your own Ollama server; SearXNG lookup is optional.

================================================================================
WHAT IT DOES
================================================================================

- Scan one book with up to three photos: front, spine, and back.
- Queue books while another scans; the queue survives restarts.
- Review title, author, ISBN, and text corrections before saving.
- Search/edit your library and choose which books are available to trade.
- Invite friends, browse their libraries, and request book-for-book swaps.
- Transfer ownership and photos after both people confirm the physical exchange.

================================================================================
QUICK START & RUNNING LOCALLY
================================================================================

Use Linux/WSL and Python 3.12. Install Ollama separately and download the models:

  ollama pull gemma3:12b
  ollama pull gemma3:1b

  git clone https://github.com/maxmocarski/Book-Scanner.git
  cd Book-Scanner
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
  OLLAMA_HOST=http://127.0.0.1:11434 .venv/bin/uvicorn main:app --host 127.0.0.1 --port 8503

Open http://localhost:8503/ for the app; /docs provides developer API controls. Sign up, scan, review, and save. Use one worker: the queue and migration lock prevent multiple processes sharing the same data directory.

The primary model must support images. The default gemma3:1b second pass only handles text. A cold model or CPU inference can take longer; models are unloaded after each pass by default to reduce memory pressure.

================================================================================
DOCKER DEPLOYMENT
================================================================================

The supplied Compose file expects existing ollama and optionally searxng containers on a shared Docker network. It does NOT create those services.

  cp .env.example .env
  # Edit BOOKBRIDGE_NETWORK to your existing Docker network name.
  docker compose up -d --build

The example defaults to revolt_default. Ollama must be reachable as http://ollama:11434 on that network; adjust OLLAMA_HOST in Compose if its service name differs. BookBridge listens on localhost port 8503 and stores its data in a named volume.

For an existing installation managed by another stack, keep that stack's Compose service and data mount. Update only this app's code and rebuild its service; don't switch data volumes accidentally.

--- Existing guzdekai Installation ---

BookBridge's source is ~/bookbridge; the active Compose file is ~/revolt/docker-compose.yml with build: ../bookbridge and ../bookbridge/data:/data.

  cd ~/bookbridge
  git pull
  cd ~/revolt
  sudo docker compose up -d --build --no-deps bookbridge

This rebuilds BookBridge separately from ReVolt. The repository cleanup does not change the database schema, API paths, container port, or mounted data.

================================================================================
TECHNICAL REFERENCE
================================================================================

--- Corrections and ISBNs ---

The result includes metadata, original_metadata, a corrections list with before/after values, warnings, source URLs/snippets, and an optional lookup_suggestion.

- ISBNs read with common OCR mistakes such as O for 0, or I/l/| for 1, can be repaired ONLY WHEN the resulting number passes ISBN-10/ISBN-13 validation. No digit padding or invented check digits.
- The lighter model can make small title/author edits, such as "F. Sc0tt Fitzgerald" -> "F. Scott Fitzgerald". Large rewrites are rejected. Names and deliberate title spelling may still be miscorrected; the original and applied edits remain visible.
- A secondary-model ISBN cannot replace a valid photographed ISBN. Missing/invalid photographed ISBNs stay null unless deterministic character repair succeeds.
- Lookup metadata stays in a SEPARATE SUGGESTION. Suggested fields must occur in cited snippets, and suggested ISBNs must pass checksum validation. Snippets can still describe the wrong book or edition; suggestions are explicitly unverified. Choose/correct fields yourself in the save request.
- ISBN checksum validation proves syntax, not book identity or edition. ISBNs are optional at save time. Title and author require user input if unreadable.

Note: This is OCR cleanup, not a guarantee of bibliographic accuracy. No barcode decoder or dedicated catalog API is included yet.

--- Configuration Variables ---

Variable                       Default                           Meaning
----------------------------------------------------------------------------------------------------
OLLAMA_HOST                    http://localhost:11434 (locally)  Ollama URL
                               http://ollama:11434 (in Compose)
BOOKBRIDGE_MODEL               gemma3:12b                        Primary vision model
BOOKBRIDGE_TEXT_MODEL          gemma3:1b                         Lighter text-only second pass
BOOKBRIDGE_ENRICHMENT          cleanup                           Default cleanup, lookup, or off
SEARXNG_URL                    http://searxng:8080               Search endpoint for lookup mode
BOOKBRIDGE_KEEP_ALIVE          0                                 Unload each model after inference;
                                                                 use 5m if both fit comfortably
BOOKBRIDGE_MODEL_TIMEOUT       180                               Timeout in seconds per model pass
BOOKBRIDGE_MAX_PENDING_PER_USER 100                              Max queued/processing jobs/user
BOOKBRIDGE_MAX_PENDING         500                               Max queued/processing jobs overall
BOOKBRIDGE_DATA                ./data (locally)                  Persistent SQLite data directory
                               /data (in Docker)

Compose directly exposes the model/mode/keep-alive variables. Add the others to its environment: block if changing them. Timeout excludes waiting in the queue. Default unloading reduces pressure when both models cannot fit in memory but adds reload latency for each book. No Ollama model weights are bundled.

--- Search Integration (SearXNG) ---

Lookup mode requires JSON results enabled in the existing SearXNG settings.yml:

  search:
    formats:
      - html
      - json

Merge this into existing settings and restart SearXNG. Lookup failures fall back to text cleanup. Search suggestions are unverified and may describe another edition.

================================================================================
EXISTING DATA & MIGRATION
================================================================================

On startup, 0.1 data is migrated in one transaction: saved books become one-front-photo records, unexpired old drafts become ready scan results, and accounts/friends/trades stay intact. Migration is idempotent. The old image column/drafts table are removed after copying, so DO NOT run the old application against the migrated database.

Before upgrading an already deployed 0.1 instance, stop it and copy its data out:

  sudo docker compose stop bookbridge
  sudo docker cp bookbridge:/data ./bookbridge-data-backup-before-v02

Keep the backup outside your Git repository. Update code, then rebuild/start using the same Compose project/data volume. If reverting to 0.1, restore that pre-upgrade backup too. Do not delete the named data volume when updating. If you originally deployed BookBridge inside a different stack, reuse its existing volume explicitly rather than accidentally creating a new empty one.

Ready/failed scan results and their unsaved photos expire 24 hours AFTER PROCESSING FINISHES, with cleanup approximately every minute and at startup. Waiting/in-flight jobs do not expire while processing; cancel them to free storage. Saving transfers photos to the catalog; discarding/deleting a result cascades removal of its photo rows. Persistent deleted SQLite pages/backups are not secure-erased automatically.

================================================================================
PHONE ACCESS & PRIVACY
================================================================================

Camera capture requires HTTPS or localhost. Use your own private HTTPS proxy, such as Tailscale Serve, for a phone. You can upload photos when live camera access is unavailable. Desktop users can use an SSH localhost tunnel.

Accounts and book photos are private; accepted friends can see each other's entire collections. Invitation codes are single-use and expire after 24 hours. The backend sends no email or other messages. Lookup mode sends title/author or ISBN queries through SearXNG; photos stay with your Ollama server.

Public hosting needs additional controls. Registration is currently open, and there are no public-facing rate limits, account recovery or total storage quotas. A public link permits strangers to register and submit scans. Model output, ISBN checksums and search snippets do not guarantee the correct edition: review before saving.

================================================================================
PROJECT LAYOUT
================================================================================

Path                  Purpose
--------------------------------------------------------------------------------
main.py               API, frontend serving, accounts, library, and trades
scanning.py           Persistent queue, image processing, and AI/search passes
schema.py             SQLite tables and migration
static/               Web interface, styles, JavaScript, and icon
tests/                Backend regressions and disposable browser checks
docs/REFERENCE.md     Configuration, ISBN safeguards, and data migration
docs/ROADMAP.md       Ideas for future improvements
Dockerfile            Container deployment
compose.yaml          Container deployment configuration
.env.example          Example configuration; copy to private .env

================================================================================
TESTING
================================================================================

  .venv/bin/pip install -r requirements-dev.txt
  .venv/bin/python -m pytest -q

Browser checks use a temporary database and fake model/search responses. DO NOT run them against your real library.

  # Terminal 1
  .venv/bin/python tests/ui/mock_server.py

  # Terminal 2 (development dependencies only)
  npm install --no-save playwright
  npx playwright install chromium
  node tests/ui/run.cjs

No JavaScript build step or Node dependency is required to run the actual app. AI/browser tests use mocked inference and do not measure live recognition quality.
