# BookBridge 0.5 — phone usability update

## What changed

- Removed the camera framing overlay. HTTPS camera capture and photo uploads remain available.
- Sections start closed and close again when changing pages. Settings use switches; dialogs, forms, admin controls, and bottom navigation fit smaller screens.
- First sign-in asks for first and last name; town/city is optional. Names and location are saved on the server, not just in the browser.
- Quick Add comes first in Friends. Browse books opens that person's collection; My library returns to your own.
- Ready scans warn about possible duplicates already saved or awaiting review in the same library. Accept all keeps each physical copy. Catalog cards group matching editions and open a list of individual copies.
- Known ISBN-10 and equivalent ISBN-13 editions group together. Different ISBNs stay separate. Books without ISBNs group by normalized title and author, separately from known ISBNs. Check editions manually when ISBNs are missing.
- Verified-email password recovery and private administrator reset codes are available from Forgot password.
- Admins can manage shared-library members and permanently delete a shared library, including its books, photos, scans, membership, and associated reading/trade records. Personal libraries remain intact. Deletion requires typing the exact library name. Database backups may still contain deleted information.

## Files to upload

Preserve these paths when uploading the changed-files ZIP to GitHub:

- `api/main.py`
- `api/community.py`
- `api/mobile.py` (new)
- `api/recover_account.py` (new)
- `static/index.html`
- `static/app.css`
- `static/app.js`
- `static/community.js`
- `static/mobile.js` (new)
- `tests/test_mobile.py` (new)
- `tests/ui/run.cjs`
- `README.md`
- `docs/UPGRADE-0.5.md` (new)

No changes to your server Compose configuration are required. Keep the existing data mount and admin/SMTP environment variables. The new columns and password-reset table are added automatically on startup. Existing accounts will be asked to complete their names once.

## Update guzdekai

After uploading/committing the files to GitHub, first back up the existing database while BookBridge is stopped:

```bash
cd ~/revolt
sudo docker compose stop bookbridge
backup_dir="$HOME/bookbridge-backup-$(date +%Y%m%d-%H%M%S)"
sudo docker cp bookbridge:/data "$backup_dir"
```

Then update and rebuild only BookBridge:

```bash
cd ~/bookbridge
git pull --ff-only
```

Continue only after the pull succeeds:

```bash
cd ~/revolt
sudo docker compose config --quiet && sudo docker compose up -d --build --no-deps bookbridge
curl --retry 10 --retry-connrefused --retry-delay 1 http://127.0.0.1:8503/health
```

ReVolt, Ollama, and SearXNG do not need restarting. Open your existing HTTPS address on the iPhone and reload. Assets are versioned to refresh the browser cache.

If updating fails before the rebuild, `sudo docker compose start bookbridge` from `~/revolt` starts the previous container again. Keep the backup outside the repository.

## Recover an account

For ordinary users: Settings → Admin → Accounts → search → Reset password. Share the displayed code privately after checking the requester's identity. The user selects Forgot password, enters their username, code, and new password.

Codes expire after 30 minutes, work once, and replace any previous reset code. Successful reset signs out all existing sessions. Existing passwords cannot be retrieved.

Administrator accounts use verified-email recovery or this server-console fallback:

```bash
sudo docker exec bookbridge python -m api.recover_account max
```

Replace `max` with the account username. The command prints a private reset code; do not post it publicly. Banned accounts must be unbanned before recovery.

Email recovery requires a saved, verified email address and working SMTP settings. Until then, use admin-issued codes. SMTP delivery was tested with a mock, not your mail provider.

## Validation

All 38 backend tests and Chromium phone-emulation flows passed. Backend regression tests cover profile persistence, duplicate scope, ISBN grouping, reset expiration/single use/session revocation, verified-email recovery, and deletion while a scan is running. Browser checks use a disposable database and mocked inference, never the real library.

The browser suite supports Chromium phone emulation and WebKit:

```bash
# Start the disposable server in another terminal first.
python tests/ui/mock_server.py
# Then:
npm install --no-save playwright
npx playwright install chromium
node tests/ui/run.cjs
# On a host with WebKit system dependencies installed:
BOOKBRIDGE_BROWSER=webkit node tests/ui/run.cjs
```

Physical iPhone/Safari camera behavior still needs checking on your phone. Phone emulation does not replace that device check.
