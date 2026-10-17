# Optional shelf field — 0.5.1

This update builds on the 0.5 iPhone update. Upload the files from the changed-files ZIP into their matching GitHub folders.

## Using it

Scan a book and optionally enter a shelf, such as “Living room, shelf 2”. It stays filled for the next scan so you can scan several books on the same shelf; change or clear it when moving shelves. Signing out clears this input.

The shelf is saved with each queued scan and physical book copy. You can change it while reviewing or in Book details. Accept all preserves each scan's shelf. Both personal and shared libraries support it. Shelf names appear in the queue, catalog, and individual copy details; library search includes shelf names.

Copies still group by edition, even when on different shelves. Completing a trade clears the previous owner's shelf from the transferred books.

The field is optional and limited to 100 characters. Existing books start with a blank shelf. Database columns are added automatically; no Compose edits are needed.

## Changed files

- api/main.py
- api/schema.py
- core/scanning.py
- static/index.html
- static/app.js
- static/mobile.js
- tests/test_shelves.py (new)
- tests/ui/run.cjs
- docs/UPGRADE-0.5.1.md (new)

## Deploy after committing to GitHub

Keep a backup of your existing data before upgrading. From your server:

```bash
cd ~/bookbridge
git pull --ff-only
```

After the pull succeeds:

```bash
cd ~/revolt
sudo docker compose up -d --build --no-deps bookbridge
curl --retry 10 --retry-connrefused --retry-delay 1 http://127.0.0.1:8503/health
```

Reload the app on your phone to load the versioned assets.

## Validation

All 40 backend tests passed, including shelf persistence through processing, individual saving, editing, and bulk saving to personal/shared libraries, plus migration and length validation. JavaScript syntax checks passed. Browser test coverage was extended for shelf entry/display; this new browser flow was not run in this environment.
