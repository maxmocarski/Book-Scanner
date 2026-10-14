# Technical reference

## Corrections and ISBNs

The result includes `metadata`, `original_metadata`, a `corrections` list with before/after values, warnings, source URLs/snippets, and an optional `lookup_suggestion`.

- ISBNs read with common OCR mistakes such as `O` for `0`, or `I`/`l`/`|` for `1`, can be repaired **only when the resulting number passes ISBN-10/ISBN-13 validation**. No digit padding or invented check digits.
- The lighter model can make small title/author edits, such as `F. Sc0tt Fitzgerald` → `F. Scott Fitzgerald`. Large rewrites are rejected. Names and deliberate title spelling may still be miscorrected; the original and applied edits remain visible.
- A secondary-model ISBN cannot replace a valid photographed ISBN. Missing/invalid photographed ISBNs stay null unless deterministic character repair succeeds.
- Lookup metadata stays in a **separate suggestion**. Suggested fields must occur in cited snippets, and suggested ISBNs must pass checksum validation. Snippets can still describe the wrong book or edition; suggestions are explicitly unverified. Choose/correct fields yourself in the save request.
- ISBN checksum validation proves syntax, not book identity or edition. ISBNs are optional at save time. Title and author require user input if unreadable.

This is OCR cleanup, not a guarantee of bibliographic accuracy. No barcode decoder or dedicated catalog API is included yet.

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

## Existing data and migration

On startup, 0.1 data is migrated in one transaction: saved books become one-front-photo records, unexpired old drafts become ready scan results, and accounts/friends/trades stay intact. Migration is idempotent. The old image column/drafts table are removed after copying, so **do not run the old application against the migrated database**.

Before upgrading an already deployed 0.1 instance, stop it and copy its data out:

```bash
sudo docker compose stop bookbridge
sudo docker cp bookbridge:/data ./bookbridge-data-backup-before-v02
```

Keep the backup outside your Git repository. Update code, then rebuild/start using the same Compose project/data volume. If reverting to 0.1, restore that pre-upgrade backup too. Do not delete the named data volume when updating. If you originally deployed BookBridge inside a different stack, reuse its existing volume explicitly rather than accidentally creating a new empty one.

Ready/failed scan results and their unsaved photos expire 24 hours **after processing finishes**, with cleanup approximately every minute and at startup. Waiting/in-flight jobs do not expire while processing; cancel them to free storage. Saving transfers photos to the catalog; discarding/deleting a result cascades removal of its photo rows. Persistent deleted SQLite pages/backups are not secure-erased automatically.


## Search integration

Lookup mode requires JSON results enabled in the existing SearXNG `settings.yml`:

```yaml
search:
  formats:
    - html
    - json
```

Merge this into existing settings and restart SearXNG. Lookup failures fall back to text cleanup. Search suggestions are unverified and may describe another edition.
