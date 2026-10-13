# BookBridge — private book catalog and swaps

A backend inspired by Max Mocarski's [ReVolt](https://github.com/maxmocarski/Revolt). It reuses the same approach: FastAPI sends camera photos to a self-hosted Gemma vision model through Ollama. This is a separate implementation and does not modify ReVolt.

## Included

- Register/login with hashed passwords and expiring bearer sessions.
- Photograph **one physical book per scan**. Upload its cover plus an optional back/copyright-page photo for the ISBN.
- Gemma extracts visible title, author and ISBN into a review draft. It is instructed to leave missing fields null. AI may still misread or invent text: always review.
- ISBN-10 and ISBN-13 checksum validation. This validates syntax, not whether the ISBN belongs to this edition. No external metadata verification or barcode decoder yet.
- Confirm/correct metadata before saving. Each physical copy has its own ID, even if two copies share an ISBN.
- Persist **one** normalized JPEG with each saved book in SQLite. The detail photo is never persisted. EXIF metadata is stripped. Drafts expire after 24 hours.
- Private collections. Accepted friends can see each other's entire collection and photos; only books marked available may be traded. New books default to unavailable.
- Single-use, 24-hour invitation codes; share them yourself with people you know. No public user directory or automatic messages.
- One-for-one swaps: propose → recipient accepts → both confirm physical handoff → ownership transfers atomically. Books are reserved on acceptance; competing proposals are cancelled.
- Either person can cancel before completion. Removing friendship cancels pending/accepted swaps and removes photo access.
- Interactive API docs at `/docs`. **No camera frontend or mobile app is included yet.**

## Start on your existing Ollama server

Python 3.12 is recommended. Gemma runs on the server, not on the phone.

```bash
cd bookbridge
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
ollama pull gemma3:12b
OLLAMA_HOST=http://127.0.0.1:11434 BOOKBRIDGE_DATA=./data \
  .venv/bin/uvicorn main:app --host 127.0.0.1 --port 8503
```

Open `http://127.0.0.1:8503/docs`. The service uses 8503 so ReVolt can remain on 8502. To use another existing vision model, set `BOOKBRIDGE_MODEL`. Ollama must have that model installed. No Ollama server/model is bundled with the download.

## Try the complete flow in API docs

1. Call `POST /auth/register` with a username and a password of at least 12 characters.
2. Copy `access_token`. Click **Authorize**, enter the token, and authorize. Keep the token private.
3. Call `POST /scans` with a `cover` photo. Optionally include `details` with the ISBN page/back. A cold Gemma model can take a while.
4. Copy `scan_id`, then call `POST /scans/{scan_id}/save` with the reviewed fields:

```json
{
  "title": "The Great Gatsby",
  "author": "F. Scott Fitzgerald",
  "isbn": "9780743273565",
  "available": true
}
```

If the book has no readable ISBN, send `null`. Title and author require user input if Gemma cannot read them. Saving consumes the draft; repeating save cannot add a duplicate copy accidentally.

5. `GET /books` lists your books and their IDs. Photo endpoints require the same bearer token. A frontend should fetch photos with an Authorization header and render a Blob URL; a plain unauthenticated `<img src>` will not work.
6. Create an invitation with `POST /friends/invites`. Have your friend create their own account and submit the code to `POST /friends/accept`.
7. `GET /friends` shows friend IDs; `GET /books?owner_id=FRIEND_ID` shows that friend's collection.
8. Each person adds an available book. `POST /trades` with `wanted_book_id` (the friend's copy) and `offered_book_id` (your copy) creates a proposal.
9. The friend calls `/trades/{trade_id}/accept`. After exchanging the physical books, **each** person calls `/trades/{trade_id}/confirm-handoff`. The second confirmation transfers both copies and marks them unavailable in their new owners' collections.

Use `PATCH /books/{book_id}` to replace metadata/availability; include title and author. Use `/trades/{trade_id}/cancel` to decline/cancel. Books with trade history cannot currently be deleted; mark them unavailable instead. This preserves the trade record.

## Docker

```bash
docker compose up -d --build
```

The named volume persists the database and photos. Ollama must be reachable **from inside the container**. The default `host.docker.internal:11434` only works if the host Ollama listener is reachable on the Docker host gateway; a listener bound solely to host `127.0.0.1` is not reachable there.

For your existing Docker Ollama setup, put BookBridge on the same Docker network and set `OLLAMA_HOST=http://ollama:11434`. For example, add this service to the compose stack containing Ollama, adjusting its build path:

```yaml
  bookbridge:
    build: ./bookbridge
    restart: unless-stopped
    ports:
      - "127.0.0.1:8503:8503"
    environment:
      OLLAMA_HOST: http://ollama:11434
      BOOKBRIDGE_MODEL: gemma3:12b
    volumes:
      - bookbridge-data:/data
```

Also declare `bookbridge-data:` under that stack's top-level `volumes`. Both services must share a network. Do not expose Ollama publicly to make this work.

## Storage and privacy

The server saves accounts, friendships, book images and metadata, and trade records in `BOOKBRIDGE_DATA/bookbridge.sqlite3`. Unlike ReVolt's phone-local scan history, this catalog lives on the server so ownership and trades can be shared across accounts/devices. Back up the entire data directory while the app is stopped. Named-volume data survives ordinary Docker restarts; deleting the volume deletes the catalog.

Draft images are deleted when saved/discarded or during expiry cleanup. External catalog services are not contacted. Invitation codes and bearer tokens are stored as hashes. Passwords use salted scrypt. Logout revokes the current token; sessions last seven days.

## Limits of this first version

Designed for a small trusted group behind private HTTPS access, such as your existing Tailscale setup. Use one Uvicorn worker. It is not ready for unrestricted public registration: no rate limiting, registration allowlist, email verification, password reset, account deletion/export, storage quotas, or account administration. API docs are development tools, not an end-user UI. For a future browser camera frontend, serve it through HTTPS and avoid putting access tokens in URLs.

The model can only use visible evidence; an ISBN often requires a second photo. Checksum validation cannot prove edition accuracy. Live Gemma recognition depends on your server hardware and model; automated tests mock it. No live server/GPU test was performed here. Docker configuration is provided but has not been launched here.

SQLite serializes swap updates to prevent two accepted trades reserving the same copy. Images are stored as BLOBs for a simple atomic save; large deployments should use private object storage and a larger database. Lending, multi-book swaps, messaging, shelf batch scanning, barcode decoding, metadata lookup, and automatic valuation are not implemented.

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

Tests cover photo privacy, scan/save, invalid uploads, ISBN checks, authentication, invite consumption, friend removal, swap authorization, reservations, both-party confirmation, and Ollama request structure using mocked inference.

## API reference

| Method | Path | Purpose |
|---|---|---|
| POST | `/auth/register`, `/auth/login`, `/auth/logout` | Account/session lifecycle |
| GET | `/me` | Current user ID and username |
| POST | `/scans` | Review draft from cover + optional details |
| POST | `/scans/{id}/save` | Save reviewed book and one photo |
| DELETE | `/scans/{id}` | Discard draft |
| GET | `/books` | Own collection, or friend's via owner_id |
| GET | `/books/{id}/image` | Authenticated JPEG |
| PATCH / DELETE | `/books/{id}` | Edit / remove eligible own book |
| POST | `/friends/invites`, `/friends/accept` | Invite and consent to friendship |
| GET | `/friends` | Accepted friends |
| DELETE | `/friends/{id}` | End friendship and cancel open swaps |
| POST / GET | `/trades` | Propose / list own swaps |
| POST | `/trades/{id}/accept` | Recipient reserves both books |
| POST | `/trades/{id}/cancel` | Either party declines/cancels |
| POST | `/trades/{id}/confirm-handoff` | Confirm physical exchange |
| GET | `/health` | Service liveness (does not probe Gemma) |
