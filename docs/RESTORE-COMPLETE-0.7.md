# Complete BookBridge 0.7 application bundle

This bundle includes every application Python module and frontend asset, including core/shelves.py and static/catalog.js from earlier updates. Use it to repair an incomplete set of uploaded files.

Extract the ZIP, open the extracted folder, and upload the folders and files inside it to the root of maxmocarski/Book-Scanner on GitHub. Keep api/, core/, static/, tests/, and docs/ as folders. Commit all uploaded files together. In particular, verify core/shelves.py and static/catalog.js appear at those exact paths.

The bundle contains application code, dependencies, tests, and documentation. It contains no database, account data, secrets, or active server Compose configuration. Keep using ~/revolt/docker-compose.yml and the existing ~/bookbridge/data mount.

After committing:

```bash
cd ~/bookbridge
git pull --ff-only
ls core/shelves.py static/catalog.js
```

After the pull succeeds and both files exist:

```bash
cd ~/revolt
sudo docker compose up -d --build --no-deps bookbridge
```

Then check:

```bash
curl --retry 10 --retry-all-errors --retry-delay 1 --max-time 5 http://127.0.0.1:8503/health
```

Expect {"status":"ok"}. If startup still fails, collect sudo docker compose logs --tail=80 bookbridge. Your existing backup remains available at ~/bookbridge-before-v07-20261018-013803. The missing-module crash occurred during import, before application startup migrations.
