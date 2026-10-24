"""Schema and transactional migration from BookBridge 0.1 (one photo/draft)."""
import json
import time

SCHEMA = '''
CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, username TEXT UNIQUE, salt TEXT, password_hash TEXT);
CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, user_id TEXT REFERENCES users(id), expires INTEGER);
CREATE TABLE IF NOT EXISTS invites(code_hash TEXT PRIMARY KEY, user_id TEXT REFERENCES users(id), expires INTEGER);
CREATE TABLE IF NOT EXISTS friends(a TEXT REFERENCES users(id), b TEXT REFERENCES users(id), PRIMARY KEY(a,b));
CREATE TABLE IF NOT EXISTS books(id TEXT PRIMARY KEY, owner TEXT REFERENCES users(id), title TEXT, author TEXT, isbn TEXT, available INTEGER, created INTEGER, scan_audit TEXT DEFAULT '{}');
CREATE TABLE IF NOT EXISTS book_images(book_id TEXT REFERENCES books(id) ON DELETE CASCADE, position INTEGER CHECK(position BETWEEN 0 AND 2), view TEXT CHECK(view IN ('front','spine','back')), image BLOB NOT NULL, PRIMARY KEY(book_id,position), UNIQUE(book_id,view));
CREATE TABLE IF NOT EXISTS scans(seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, owner TEXT REFERENCES users(id), status TEXT CHECK(status IN ('queued','identifying','enriching','ready','failed')), enrichment_mode TEXT NOT NULL, created INTEGER NOT NULL, queued_at REAL NOT NULL, expires INTEGER, metadata TEXT DEFAULT '{}', original_metadata TEXT DEFAULT '{}', warnings TEXT DEFAULT '[]', corrections TEXT DEFAULT '[]', sources TEXT DEFAULT '[]', lookup_suggestion TEXT DEFAULT 'null', error TEXT);
CREATE TABLE IF NOT EXISTS scan_images(scan_id TEXT REFERENCES scans(id) ON DELETE CASCADE, position INTEGER CHECK(position BETWEEN 0 AND 2), view TEXT CHECK(view IN ('front','spine','back')), image BLOB NOT NULL, PRIMARY KEY(scan_id,position), UNIQUE(scan_id,view));
CREATE TABLE IF NOT EXISTS trades(id TEXT PRIMARY KEY, sender TEXT REFERENCES users(id), recipient TEXT REFERENCES users(id), wanted TEXT REFERENCES books(id), offered TEXT REFERENCES books(id), status TEXT, sender_confirm INTEGER DEFAULT 0, recipient_confirm INTEGER DEFAULT 0, created INTEGER);
CREATE INDEX IF NOT EXISTS books_owner ON books(owner);
CREATE INDEX IF NOT EXISTS trades_books ON trades(wanted,offered,status);
CREATE INDEX IF NOT EXISTS scans_owner ON scans(owner);
CREATE INDEX IF NOT EXISTS scans_queue ON scans(status,queued_at,seq);
'''

def initialize(db):
    with db() as c:
        # Avoid executescript's implicit commit so migration is one transaction.
        for sql in SCHEMA.split(';'):
            if sql.strip():
                c.execute(sql)
        columns = {row['name'] for row in c.execute('PRAGMA table_info(books)')}
        if 'scan_audit' not in columns:
            c.execute("ALTER TABLE books ADD COLUMN scan_audit TEXT DEFAULT '{}'")
        if 'image' in columns:
            c.execute("INSERT OR IGNORE INTO book_images(book_id,position,view,image) SELECT id,0,'front',image FROM books WHERE image IS NOT NULL")
            c.execute('ALTER TABLE books DROP COLUMN image')
        if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='drafts'").fetchone():
            for row in c.execute('SELECT * FROM drafts').fetchall():
                if row['expires']<=int(time.time()):
                    continue
                c.execute("INSERT OR IGNORE INTO scans(id,owner,status,enrichment_mode,created,queued_at,expires,metadata,original_metadata,warnings) VALUES(?,?,'ready','off',?,?,?,?,?,?)",
                          (row['id'],row['owner'],int(time.time()),time.time(),row['expires'],row['metadata'],row['metadata'],json.dumps(['Migrated from the previous version; review before saving.'])))
                c.execute("INSERT OR IGNORE INTO scan_images VALUES(?,0,'front',?)",(row['id'],row['image']))
            c.execute('DROP TABLE drafts')
        c.execute("UPDATE scans SET status='queued',error=NULL,expires=NULL WHERE status IN ('identifying','enriching')")
        for table in ('books','scans'):
            if 'shelf' not in {r['name'] for r in c.execute('PRAGMA table_info('+table+')')}:
                c.execute("ALTER TABLE "+table+" ADD COLUMN shelf TEXT NOT NULL DEFAULT ''")
        if 'genre' not in {r['name'] for r in c.execute('PRAGMA table_info(books)')}:
            c.execute("ALTER TABLE books ADD COLUMN genre TEXT NOT NULL DEFAULT ''")
        from core import shelves
        shelves.initialize(c)
        from core import batch
        batch.initialize(c)
        c.execute('PRAGMA user_version=2')

