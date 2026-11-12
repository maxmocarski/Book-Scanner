# BookBridge code analysis — 2026-11-06

A to-do list from a full review of the repo at commit `557d0bc`. Nothing has been fixed yet.
Tick items off as they're done, and re-run the checks at the bottom to confirm.

**Summary:** the security basics are sound (scrypt passwords, hashed tokens, parameterized SQL,
no `innerHTML` in the frontend, ownership/friend/library checks on every route). The main problems
are how SQLite is used under load, a few abuse/lockout paths, a vulnerable Pillow pin, and repo/test drift.

---

## Step 1 — Quick cleanup (small, low risk)

- [ ] **Raise the Pillow pin.** `requirements.txt` has `Pillow>=11,<13`; `pip-audit` reports 39 advisories
      against 12.3.0, fixed in 13.0.0. The test suite gives the same result on 13.0.0. Change to `Pillow>=13,<14`.
- [ ] **Restrict image formats at parse time.** `core/scanning.py:73` — use
      `Image.open(BytesIO(raw), formats=('JPEG', 'PNG', 'WEBP'))` so other formats are never parsed.
- [ ] **Delete `tests/test_shelevs.py`.** It contains JavaScript, so `pytest` stops at collection and the
      README test command can never pass.
- [ ] **Fix or delete the stale test** `tests/test_arrangements.py`. It calls `POST /books/{id}/genre` and a custom
      `shelf_position`, both removed on purpose in commit `4217605` (genres moved to the queue in `core/genres.py`).
- [ ] **Rename `download` to `.gitignore`** (it's the intended version: it adds `node_modules/`).
- [ ] **Remove duplicate browser tests**: `bookshelf.cjs`, `public.cjs`, `run.cjs` exist identically in `tests/` and
      `tests/ui/`; `experience.cjs` differs between the two — keep one copy.
- [ ] **Correct the README:**
  - run command `uvicorn main:app` → `uvicorn api.main:app`
  - `.env.example`, `docs/REFERENCE.md`, `docs/ROADMAP.md` are referenced but don't exist
  - "no email / no rate limits / no account recovery" is out of date — all three exist now
  - project layout table still lists `main.py`, `scanning.py`, `schema.py` at the root
  - document `BOOKBRIDGE_ADMINS` and `SMTP_HOST`, `SMTP_FROM`, `SMTP_PORT`, `SMTP_SSL`, `SMTP_USER`, `SMTP_PASSWORD`
- [ ] **Pass admin/SMTP settings in `compose.yaml`** — without them a fresh Docker install has no admin and no email.
- [ ] **Add a test for `api/recover_account.py`** (0% coverage).
- [ ] **Add CI** (e.g. a GitHub Action running `pytest`). Most commits are web uploads, which is how the misplaced files got in.
- [ ] Tidy: update `TODO.txt` (several items are done: forgot password, quick add, switches); align the API
      version (`0.7.0` in `api/main.py`) with the UI asset version (`0.8.4`); consider pinning exact dependency versions.

## Step 2 — Database concurrency (biggest real-world issue)

- [ ] **Stop taking the write lock for reads.** `db()` in `api/main.py:33` runs `BEGIN IMMEDIATE` for every request,
      including reads, and journal mode is `delete`. Measured: a plain `GET /friends` waited 1.5 s while another
      connection held the lock. Fix: `PRAGMA journal_mode=WAL` once at startup, and a read-only helper with no
      `BEGIN IMMEDIATE` for GET routes.
- [ ] **Don't run SQLite on the event loop.** `async def scan()` (`api/main.py:225`) and `Scanner.process_next`
      (`core/scanning.py:267-280`) and `core/genres.py:45` call the DB directly inside async code.
      Measured: under lock pressure `/health` (which never touches the DB) went from ~20 ms to **5.4 s**.
      Fix: wrap those calls in `await asyncio.to_thread(...)`.
- [ ] **Hash passwords outside the transaction in login.** `api/main.py:152-155` runs scrypt while holding the lock
      (register already does it correctly).

## Step 3 — Polling cost and background tasks

- [ ] **Make duplicate detection cheap.** The frontend polls `GET /scans?limit=500` every 2.5 s (`static/app.js:189`).
      For each ready scan, `duplicate_info` (`api/mobile.py:36-40`) re-reads the whole library and all ready scans in
      Python, under the lock. Measured with 2,000 books: 102 ms at 50 ready scans, 457 ms at 200.
      Fix: compute edition keys once per request (or store an `edition_key` column with an index).
- [ ] **Keep background loops alive.** `community.email_loop` and `main.expiry_loop` have no `try/except`; one
      `database is locked` error stops them permanently (confirmed), and the error resurfaces at shutdown because
      `lifespan` only suppresses `CancelledError`. Fix: catch and log exceptions inside each loop iteration.

## Step 4 — Abuse and lockout paths

- [ ] **Upload size cap before auth.** Unauthenticated `POST /scans` had its full 300 MB body read before the 401
      (FastAPI parses the body before dependencies). Fix: a middleware that rejects large `Content-Length` /
      streamed bodies, and/or a reverse-proxy limit.
- [ ] **Login lockout.** `api/main.py:150` limits by username: 20 bad attempts by anyone → the real user gets 429.
      Same pattern for password recovery (3/hour per username, `api/mobile.py:87`). Consider limiting by IP +
      username, or adding a delay instead of a hard block.
- [ ] **Write rate limit keys on the raw `Authorization` header** (`api/community.py:245`), so anonymous traffic with
      random tokens is never limited (200 random tokens → 200×401, no 429). Key on the resolved user ID, or IP when
      unauthenticated.
- [ ] **Client IP behind Docker/proxy.** Rate limits use `request.client.host`; behind Docker everyone likely shares
      one IP. Configure uvicorn `--proxy-headers --forwarded-allow-ips=<proxy>` to match the deployment.
- [ ] **Admin by username** (`api/community.py:24`): anyone can register a name listed in `BOOKBRIDGE_ADMINS` that
      isn't taken yet. Register admin accounts before setting the variable, or switch to an admin flag in the DB.
- [ ] Add security headers (CSP, `X-Content-Type-Options: nosniff`, `X-Frame-Options`).

## Step 5 — Behavior bugs

- [ ] **Any book edit cancels pending trades** (`api/main.py:380`). With autosave, changing just the shelf or genre
      cancels the trade with no notice. Only cancel when title, author or ISBN change.
- [ ] **Books with any trade history can never be deleted** (`api/main.py:386`), even if every trade was cancelled
      (returned 409). Only block when a trade is pending/accepted.
- [ ] Missing features: change password while logged in; delete account.

## iPhone notes (from reading the code — not tested on a device)

- [ ] Login token is in `sessionStorage` (`static/app.js:5`), so closing the tab/Safari evicting it logs the user out.
- [ ] `setPhoto` rejects files over 10 MB (`static/app.js:370`) *before* shrinking them to 1600 px — large iPhone photos
      are refused even though they'd be resized anyway. Move the size check after resizing.
- [ ] Run the Playwright suite with WebKit (`BOOKBRIDGE_BROWSER=webkit`) — it wasn't run during this analysis.

---

## How to re-run the checks

All of this ran on a throwaway copy and temp database — never against real data.

```bash
# Copy the repo to a scratch folder and make a Python 3.12 venv (uv shown; plain venv works too)
mkdir -p /tmp/bb-check && git archive HEAD | tar -x -C /tmp/bb-check && cd /tmp/bb-check
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt pytest-cov pyflakes pip-audit bandit

# Tests + coverage (expect: 56 passed, 1 failed until Step 1 is done)
.venv/bin/python -m pytest -q --ignore=tests/test_shelevs.py --cov=api --cov=core

# Static checks and dependency audit
.venv/bin/python -m pyflakes api core
.venv/bin/bandit -q -r api core          # B608 hits are fixed strings, not injection
.venv/bin/pip-audit -r requirements.txt  # should be clean after the Pillow bump
```

Runtime checks (start a disposable server first:
`BOOKBRIDGE_DATA=$(mktemp -d) OLLAMA_HOST=http://127.0.0.1:9 .venv/bin/uvicorn api.main:app --port 18503`):

| Check | How | Before fix |
|---|---|---|
| Read waits on write lock | Open the SQLite file in another process, run `BEGIN IMMEDIATE`, hold 1.5 s, meanwhile `GET /friends` | waits 1.5 s |
| Event loop stalls | Hold the lock in a loop (500 ms on / 30 ms off) while several users `POST /scans`; time `GET /health` | up to 5.4 s |
| Poll cost | Insert 2,000 books and 200 `ready` scans for one user; time `GET /scans?limit=500` | ~457 ms |
| Background loop death | Monkeypatch `community.send_next_email` to raise `sqlite3.OperationalError`; run `email_loop` | task ends |
| Unauthenticated upload | Send a 300 MB multipart body to `POST /scans` with no token | fully read, then 401 |
| Login lockout | 21 wrong-password logins for a user, then the correct password | 429 |
| Trade cancelled by edit | Propose a trade, then the recipient changes the shelf of their book | trade cancelled |
| Undeletable book | Cancel a trade, then `DELETE /books/{id}` | 409 |

Timings were measured on one Mac; a real server will differ.
