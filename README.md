# BookBridge 0.3 — camera scanner, private library and swaps

A FastAPI backend inspired by Max Mocarski's [ReVolt](https://github.com/maxmocarski/Revolt). Catalog your physical books using a self-hosted Gemma camera scan, then arrange book-for-book swaps with invited friends. This project is separate from ReVolt.

## Simple web interface

Open `/` for the app. It has four sections: **Scan a book**, **Queue**, **My library**, and **Friends & trades**. A responsive cream/dark-green design uses a ReVolt-style camera viewport and shutter, with three photo slots and a simple review dialog.

Sign in or register in the app. Authentication is handled automatically; you do not copy tokens or scan IDs. The session is stored in this browser tab and cleared on sign-out. Photos require authenticated requests and are displayed as local Blob URLs. All fonts, icons and assets are served by the app, with no frontend framework/build step or external CDN.

- Open the camera or upload JPG/PNG/WebP images into front, spine and back slots. Preview/remove photos before submitting. Front is required; the other two are optional.
- Queue scans without waiting for AI. The queue updates automatically every 2.5 seconds while the tab is visible.
- Review fields, OCR corrections, warnings and lookup suggestions, then save. ISBN is optional.
- Search your library, edit details/availability, or browse an invited friend's library.
- Create/copy an invitation code, accept one, request a one-for-one swap, accept/decline it, and confirm physical handoff. Both people must confirm before ownership transfers.

Camera permissions require **HTTPS or localhost**. If opening the app via a plain HTTP server IP, upload photos instead, or use a private HTTPS setup. The desktop SSH tunnel below uses localhost and supports camera access. Closing/changing tabs within the app stops the camera; backgrounding the browser also stops it. No service worker/offline cache is added.

## Update the deployed server

Upload the files from this release into the top level of your **Book-Scanner** GitHub repository, preserving the `static/` folder. Update `main.py`, `Dockerfile`, `README.md` and the new static files; include the supplied ignore files. Your server's active Compose file is still **`~/revolt/docker-compose.yml`** and its BookBridge service uses `build: ../bookbridge`, port 8503 and `../bookbridge/data:/data`. Keep that server configuration.

```bash
cd ~/bookbridge
git pull
cd ~/revolt
sudo docker compose up -d --build --no-deps bookbridge
```

This rebuilds only BookBridge and preserves the existing data folder. ReVolt remains a separate running service on 8502. No database migration is required for the frontend update. The new trade-list response adds book titles/usernames while preserving existing API fields.

From Windows PowerShell:

```powershell
ssh -L 8503:127.0.0.1:8503 mmocarski1@guzdekai
```

Keep the session open, then visit **http://localhost:8503/** (the app), rather than `/docs` (developer API controls). Existing accounts and saved books are available after sign-in.

## Validation for this release

19 backend tests passed, including frontend serving and trade labels. The Playwright browser flow passed at desktop and 390 px phone width: sign-up/sign-in, camera capture, three photos, scan/review/save/edit, invitation creation, browsing a friend’s books, swap request/acceptance, both-party handoff, transfer of all photos, and logout revocation. Browser runs use a temporary database and mocked inference/search responses.

## Scan pipeline

1. Upload **one physical book**, with a required `front` photo and optional `spine` and `back` photos. Up to three images, 10 MB each. For the ISBN, `back` can instead be a copyright-page photo.
2. The upload returns **HTTP 202** and a persistent queue ID immediately after image validation/storage. Submit another book without waiting for AI. Each book is one job; multiple books need multiple submissions.
3. A single worker takes jobs in FIFO order, sends all the book's photos together to `gemma3:12b`, and extracts title, author and ISBN.
4. A lighter, **text-only** `gemma3:1b` pass cleans obvious OCR/spelling/punctuation mistakes. Optional lookup mode first queries your SearXNG instance and supplies search snippets to the lighter model.
5. Poll for completion, review the result and its changes, and save the book. **All uploaded photos are kept** with the saved book.

The model passes run serially; other books wait in the queue. Normalized JPEG photos and jobs live in SQLite, not process memory. Interrupted jobs requeue on restart. Failed primary scans keep their photos and can be retried; a secondary/search failure leaves the primary result ready with a warning. Cancelling removes the job/photos immediately; an in-flight model request may still finish, but cannot recreate the deleted job.

Statuses: `queued` → `identifying` → `enriching` → `ready`, or `failed`. `queue_position` is the waiting position: 1 means next in line and excludes the currently running book. It is null for jobs already processing/finished. Retry places a failed book at the back of the waiting queue.

## Corrections and ISBNs

The result includes `metadata`, `original_metadata`, a `corrections` list with before/after values, warnings, source URLs/snippets, and an optional `lookup_suggestion`.

- ISBNs read with common OCR mistakes such as `O` for `0`, or `I`/`l`/`|` for `1`, can be repaired **only when the resulting number passes ISBN-10/ISBN-13 validation**. No digit padding or invented check digits.
- The lighter model can make small title/author edits, such as `F. Sc0tt Fitzgerald` → `F. Scott Fitzgerald`. Large rewrites are rejected. Names and deliberate title spelling may still be miscorrected; the original and applied edits remain visible.
- A secondary-model ISBN cannot replace a valid photographed ISBN. Missing/invalid photographed ISBNs stay null unless deterministic character repair succeeds.
- Lookup metadata stays in a **separate suggestion**. Suggested fields must occur in cited snippets, and suggested ISBNs must pass checksum validation. Snippets can still describe the wrong book or edition; suggestions are explicitly unverified. Choose/correct fields yourself in the save request.
- ISBN checksum validation proves syntax, not book identity or edition. ISBNs are optional at save time. Title and author require user input if unreadable.

This is OCR cleanup, not a guarantee of bibliographic accuracy. No barcode decoder or dedicated catalog API is included yet.

## Deploy on guzdekai

The included `compose.yaml` is configured for your existing containers:

- External Docker network: `revolt_default`
- Ollama: `http://ollama:11434`
- SearXNG: `http://searxng:8080`
- BookBridge: host `127.0.0.1:8503`

Upload the **contents** of the `bookbridge` folder into the top level of your GitHub repository. Include `main.py`, `scanning.py`, `schema.py`, `Dockerfile`, `compose.yaml`, requirements and tests. Upload the extracted files, not the ZIP. Do not upload a virtual environment, private `.env`, or database/data folder. This project has not been pushed to GitHub automatically.

On the server, for a new clone (assuming that repo name):

```bash
git clone https://github.com/maxmocarski/Book-Scanner.git ~/bookbridge
cd ~/bookbridge
sudo docker exec ollama ollama pull gemma3:12b
sudo docker exec ollama ollama pull gemma3:1b
sudo docker compose up -d --build
curl http://127.0.0.1:8503/health
```

If already cloned, use `git pull` instead of cloning again. If you already deployed 0.1, back up the existing data before updating (see migration below).

The default mode is `cleanup`. To use SearXNG lookup for all new scans, create/edit a local `.env` alongside `compose.yaml`:

```dotenv
BOOKBRIDGE_ENRICHMENT=lookup
```

Then apply it:

```bash
sudo docker compose up -d --build
```

Each submission can override that default with multipart `enrichment=cleanup`, `lookup`, or `off`. The mode is stored with the queued job. Search queries contain only ISBN or title/author; photos are sent to Ollama only. Lookup queries are forwarded by SearXNG to external search engines. Cleanup/off modes do not search the web.

### Enable JSON in SearXNG

Lookup uses `GET /search?q=...&format=json`. Your SearXNG settings must permit JSON. In the **existing** `settings.yml`, under its existing `search:` block, include:

```yaml
search:
  formats:
    - html
    - json
```

Merge these entries into existing settings instead of replacing the file or adding a second `search:` key. Restart SearXNG after changing its mounted configuration. If you need to locate the host config:

```bash
sudo docker inspect searxng --format '{{json .Mounts}}'
```

Test lookup access **from the BookBridge container**:

```bash
sudo docker exec bookbridge python -c "import httpx; r=httpx.get('http://searxng:8080/search', params={'q':'The Great Gatsby F. Scott Fitzgerald','format':'json'}, timeout=30, trust_env=False); print('HTTP',r.status_code); print(r.text[:500])"
```

A 403 often means JSON is disabled. Search results can also be unavailable because of engine/network errors. The app falls back to text cleanup and shows a warning. The included configuration assumes SearXNG shares `revolt_default`; inspect its networks if connection/DNS fails.

### Reach the API from your computer

For initial testing, keep port 8503 private and use an SSH tunnel from Windows PowerShell:

```powershell
ssh -L 8503:127.0.0.1:8503 mmocarski1@guzdekai
```

Leave that SSH session open, then visit `http://localhost:8503/docs`. Substitute the server's IP if its name does not resolve. Phone camera access requires private HTTPS; the desktop localhost tunnel supports camera access.

## Test scans using interactive docs

1. `POST /auth/register` with a username and password of at least 12 characters. Copy the returned `access_token`.
2. Click **Authorize** and enter the token. All scan/book/photo/friend/trade endpoints require bearer authentication.
3. Submit `POST /scans` with `front`, optional `spine`, optional `back`, and an optional enrichment mode. **Omit unused file fields**; do not attach empty files. Legacy `cover` (front) and `details` (back) are accepted, but cannot be combined with the equivalent new field.
4. Copy `scan_id` and submit the next book if desired. Use `GET /scans` for your queue or `GET /scans/{scan_id}` for one job. A frontend should poll every 1–2 seconds while the status is queued/identifying/enriching.
5. When status becomes `ready`, inspect `original_metadata`, `metadata`, `corrections`, `warnings`, and any lookup suggestion. `GET /scans/{scan_id}/images/{position}` lets you view the retained photos.
6. Submit `POST /scans/{scan_id}/save` with the fields you have reviewed. For example:

```json
{
  "title": "The Great Gatsby",
  "author": "F. Scott Fitzgerald",
  "isbn": "9780743273565",
  "available": true
}
```

The save response includes `book_id`; saving consumes the queued result and moves all its photos to the book **atomically**. Repeating save cannot add a duplicate accidentally. Distinct physical copies may share an ISBN and still have separate book IDs.

7. `GET /books` returns your catalog with an `images` array (view, position and URL). Position reflects uploaded order, not a fixed role: front+back produces positions 0 and 1. Use the `view` field to distinguish photos. `/books/{id}/image` remains a front-photo alias for compatibility.
8. Failed jobs can be retried with `POST /scans/{id}/retry`, or cancelled using `DELETE /scans/{id}`. Cancellation also works for queued, processing, and ready jobs.

Image URLs require Authorization. A frontend should fetch each photo with a bearer header and display its Blob URL; a plain unauthenticated `<img src>` will not work.

## Friends and physical swaps

Your collection is private until you accept friendship. Friends can see your **whole collection and all its photos**; only books marked available can be traded. New books default to unavailable.

- `POST /friends/invites` creates a single-use, 24-hour code. Share it privately yourself; the backend sends no messages.
- Your friend registers, signs in, and submits it to `POST /friends/accept`.
- `GET /friends` shows friend IDs; `GET /books?owner_id=FRIEND_ID` lists a friend's catalog.
- Each person adds an available book. `POST /trades` takes `wanted_book_id` (their copy) and `offered_book_id` (your copy).
- The recipient accepts via `/trades/{id}/accept`. Both books become reserved and competing proposals are cancelled.
- After physically exchanging the books, **each person** calls `/trades/{id}/confirm-handoff`. The second confirmation transfers both book records **including all photos**, then marks both copies unavailable in their new owners' catalogs.
- Either person can decline/cancel via `/trades/{id}/cancel`. Removing friendship cancels open trades and removes photo access.

`PATCH /books/{id}` replaces metadata and availability; include title and author. Books with trade history cannot currently be deleted: mark them unavailable instead. Book images and their original scan audit are preserved during edits.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `OLLAMA_HOST` | `http://localhost:11434` locally; `http://ollama:11434` in Compose | Ollama URL |
| `BOOKBRIDGE_MODEL` | `gemma3:12b` | Primary vision model |
| `BOOKBRIDGE_TEXT_MODEL` | `gemma3:1b` | Lighter text-only second pass |
| `BOOKBRIDGE_ENRICHMENT` | `cleanup` | Default `cleanup`, `lookup`, or `off` |
| `SEARXNG_URL` | `http://searxng:8080` | Search endpoint for lookup mode |
| `BOOKBRIDGE_KEEP_ALIVE` | `0` | Unload each model after inference; use `5m` if both models fit comfortably |
| `BOOKBRIDGE_MODEL_TIMEOUT` | `180` | Timeout in seconds per model pass |
| `BOOKBRIDGE_MAX_PENDING_PER_USER` | `100` | Maximum queued/processing jobs per user |
| `BOOKBRIDGE_MAX_PENDING` | `500` | Maximum queued/processing jobs server-wide |
| `BOOKBRIDGE_DATA` | `./data` locally; `/data` in Docker | Persistent SQLite data directory |

Compose directly exposes the model/mode/keep-alive variables. Add the others to its `environment:` block if changing them. Timeout excludes waiting in the queue. Default unloading reduces pressure when both models cannot fit in memory but adds reload latency for each book. No Ollama model weights are bundled.

## Run without Docker

Linux/Unix, Python 3.12 recommended. The single-worker lock uses `fcntl`; use Docker/WSL on Windows.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
ollama pull gemma3:12b
ollama pull gemma3:1b
OLLAMA_HOST=http://127.0.0.1:11434 BOOKBRIDGE_DATA=./data \
  .venv/bin/uvicorn main:app --host 127.0.0.1 --port 8503
```

Use **one worker**. The data-directory lock prevents multiple processes from claiming/migrating the same queue. One shared scanner handles both model passes; no Redis/Celery service is required.

## Existing data and migration

On startup, 0.1 data is migrated in one transaction: saved books become one-front-photo records, unexpired old drafts become ready scan results, and accounts/friends/trades stay intact. Migration is idempotent. The old image column/drafts table are removed after copying, so **do not run the old application against the migrated database**.

Before upgrading an already deployed 0.1 instance, stop it and copy its data out:

```bash
sudo docker compose stop bookbridge
sudo docker cp bookbridge:/data ./bookbridge-data-backup-before-v02
```

Keep the backup outside your Git repository. Update code, then rebuild/start using the same Compose project/data volume. If reverting to 0.1, restore that pre-upgrade backup too. Do not delete the named data volume when updating. If you originally deployed BookBridge inside a different stack, reuse its existing volume explicitly rather than accidentally creating a new empty one.

Ready/failed scan results and their unsaved photos expire 24 hours **after processing finishes**, with cleanup approximately every minute and at startup. Waiting/in-flight jobs do not expire while processing; cancel them to free storage. Saving transfers photos to the catalog; discarding/deleting a result cascades removal of its photo rows. Persistent deleted SQLite pages/backups are not secure-erased automatically.

## Tests and current scope

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

Tests cover queue ordering/limits, submitting while inference waits, cancellation in flight, retries/recovery, three-photo access/privacy, existing-data migration, authentication, friendship/trade reservations, both-party handoff, OCR character repair, second-pass corrections, lookup suggestions, and unavailable/invalid services. AI and search calls are mocked; no live GPU/Gemma/SearXNG or Docker deployment has been performed here.

The frontend and API are served by the same FastAPI app. It is designed for a small trusted group behind private access such as your Tailscale network. Accounts use salted scrypt, hashed bearer sessions (seven days), and logout revocation. Public deployment still needs registration controls, rate limiting, account recovery/administration, storage quotas, and HTTPS. Total retained catalog storage has no quota yet. A production proxy should limit upload request size too. No lending, messaging, multi-book swaps, shelf-batch detection, or automatic valuation is included.

## Source layout

| File | Purpose |
|---|---|
| `main.py` | Authenticated API, frontend serving, catalog, friendship and swaps |
| `static/` | Responsive HTML, CSS, JavaScript and book icon |
| `scanning.py` | Queue worker, image normalization, both models, SearXNG and correction safeguards |
| `schema.py` | Tables and migration from 0.1 |
| `compose.yaml`, `Dockerfile` | Deployment on the existing server/network |
| `.env.example` | Optional model/mode configuration |
| `tests/` | Regression tests using mocked services |

## Browser regression checks

Use the disposable mocked-model test server, **not your live library**. The browser check creates test users, scans and trades, and checks camera capture, three-photo upload, OCR review, saving/editing, invitations, ownership transfer, sign-out revocation, and phone-width layout.

```bash
# Terminal 1: temporary database, fake model/search replies
.venv/bin/python tests/ui/mock_server.py

# Terminal 2: Node + Playwright (development only)
npm install --no-save playwright
npx playwright install chromium
node tests/ui/run.cjs
```

`BOOKBRIDGE_CHROMIUM` can point to an installed Chromium executable. Browser screenshots are written to `/tmp/bookbridge-ui-check` by default; override with `BOOKBRIDGE_UI_SCREENSHOTS`. Tests use a synthetic book image and mocked inference; they do not establish real camera recognition accuracy or live server connectivity.

## References

- [Ollama Gemma 3 models](https://ollama.com/library/gemma3): 12B vision model and 1B text model.
- [Ollama Generate API](https://docs.ollama.com/api/generate): images, JSON schema output and keep-alive configuration.
- [SearXNG Search API](https://docs.searxng.org/dev/search_api.html): JSON search requests and permitted formats.
