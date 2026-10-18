"""Persistent per-library shelf numbering, allocated inside the caller's transaction."""
def key(shelf):
    return (shelf or '').strip().casefold()


def scope(owner,library_id):
    return 'library:'+library_id if library_id else 'user:'+owner


def allocate(c,shelf,owner,library_id):
    if not key(shelf): return None
    namespace=scope(owner,library_id)
    c.execute('INSERT INTO shelf_counters(scope,shelf_key,last_position) VALUES(?,?,1) ON CONFLICT(scope,shelf_key) DO UPDATE SET last_position=last_position+1',(namespace,key(shelf)))
    return c.execute('SELECT last_position FROM shelf_counters WHERE scope=? AND shelf_key=?',(namespace,key(shelf))).fetchone()[0]


def location(c,row,shelf):
    """Keep the number when the shelf is unchanged; reserve a new number on a move."""
    if not key(shelf): return None
    if key(shelf)==key(row['shelf']) and row['shelf_position'] is not None:return row['shelf_position']
    return allocate(c,shelf,row['owner'],row['library_id'])


def label(shelf,position):
    return shelf+' ('+str(position)+')' if shelf and position is not None else shelf or ''


def initialize(c):
    for table in ('books','scans'):
        if 'shelf_position' not in {r['name'] for r in c.execute('PRAGMA table_info('+table+')')}:
            c.execute('ALTER TABLE '+table+' ADD COLUMN shelf_position INTEGER')
    c.execute('CREATE TABLE IF NOT EXISTS shelf_counters(scope TEXT NOT NULL,shelf_key TEXT NOT NULL,last_position INTEGER NOT NULL,PRIMARY KEY(scope,shelf_key))')
    # Base schema runs before community's library_id migration on fresh installs.
    if not all('library_id' in {r['name'] for r in c.execute('PRAGMA table_info('+t+')')} for t in ('books','scans')):return
    rows=[]
    for table in ('books','scans'):
        rows.extend((r['created'],table,r['id'],dict(r)) for r in c.execute('SELECT * FROM '+table+" WHERE trim(shelf)<>'' AND shelf_position IS NULL"))
    for _,table,identifier,row in sorted(rows,key=lambda r:(r[0],r[1],r[2])):
        position=allocate(c,row['shelf'],row['owner'],row['library_id'])
        c.execute('UPDATE '+table+' SET shelf_position=? WHERE id=?',(position,identifier))
