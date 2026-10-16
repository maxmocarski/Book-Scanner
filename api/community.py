"""Profiles, consent-based discovery, reading journals, and moderation."""
import asyncio
import hashlib
import json
import os
import re
import secrets
import smtplib
import ssl
import time
from email.message import EmailMessage
from typing import Literal
from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator


def fail(status, detail):
    raise HTTPException(status, detail)


def admins():
    return {x.strip().lower() for x in os.getenv('BOOKBRIDGE_ADMINS', '').split(',') if x.strip()}


def initialize(db):
    with db() as c:
        for sql in '''
        CREATE TABLE IF NOT EXISTS profiles(user_id TEXT PRIMARY KEY REFERENCES users(id), display_name TEXT NOT NULL DEFAULT '', town TEXT NOT NULL DEFAULT '', discoverable INTEGER NOT NULL DEFAULT 0, private_library INTEGER NOT NULL DEFAULT 0, secondary_review INTEGER NOT NULL DEFAULT 1, review_mode TEXT NOT NULL DEFAULT 'cleanup', email TEXT NOT NULL DEFAULT '', email_verified INTEGER NOT NULL DEFAULT 0, email_notifications INTEGER NOT NULL DEFAULT 0, banned INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS friend_requests(sender TEXT REFERENCES users(id),recipient TEXT REFERENCES users(id),created INTEGER, PRIMARY KEY(sender,recipient));
        CREATE TABLE IF NOT EXISTS reading_log(user_id TEXT REFERENCES users(id), book_id TEXT REFERENCES books(id), title TEXT, author TEXT, isbn TEXT, pages_read INTEGER NOT NULL DEFAULT 0, review TEXT NOT NULL DEFAULT '', rating INTEGER, finished INTEGER NOT NULL DEFAULT 0, updated INTEGER, PRIMARY KEY(user_id,book_id));
        CREATE TABLE IF NOT EXISTS email_codes(user_id TEXT PRIMARY KEY REFERENCES users(id),code_hash TEXT,email TEXT,expires INTEGER);
        CREATE TABLE IF NOT EXISTS email_outbox(id TEXT PRIMARY KEY,user_id TEXT REFERENCES users(id),address TEXT,subject TEXT,body TEXT,kind TEXT,attempts INTEGER NOT NULL DEFAULT 0,next_attempt INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'pending');
        CREATE TABLE IF NOT EXISTS rate_limits(key TEXT PRIMARY KEY,hits INTEGER,expires INTEGER);
        CREATE TABLE IF NOT EXISTS abuse_events(id INTEGER PRIMARY KEY,created INTEGER,reason TEXT,actor TEXT);
        CREATE TABLE IF NOT EXISTS admin_audit(id INTEGER PRIMARY KEY,created INTEGER,admin TEXT,action TEXT,target TEXT);
        '''.split(';'):
            if sql.strip(): c.execute(sql)
        c.execute('CREATE TABLE IF NOT EXISTS libraries(id TEXT PRIMARY KEY,name TEXT NOT NULL,owner TEXT REFERENCES users(id),created INTEGER)')
        c.execute('CREATE TABLE IF NOT EXISTS library_members(library_id TEXT REFERENCES libraries(id),user_id TEXT REFERENCES users(id),PRIMARY KEY(library_id,user_id))')
        for table in ('books','scans'):
            if 'library_id' not in {r['name'] for r in c.execute('PRAGMA table_info('+table+')')}:
                c.execute('ALTER TABLE '+table+' ADD COLUMN library_id TEXT REFERENCES libraries(id)')
        cols = {r['name'] for r in c.execute('PRAGMA table_info(books)')}
        if 'removed' not in cols:
            c.execute('ALTER TABLE books ADD COLUMN removed INTEGER NOT NULL DEFAULT 0')
        c.execute('INSERT OR IGNORE INTO profiles(user_id) SELECT id FROM users')


def profile_for(c, me):
    c.execute('INSERT OR IGNORE INTO profiles(user_id) VALUES(?)', (me['id'],))
    row = dict(c.execute('SELECT * FROM profiles WHERE user_id=?', (me['id'],)).fetchone())
    row.pop('user_id')
    row.pop('banned')
    for key in ('discoverable','private_library','secondary_review','email_verified','email_notifications'):
        row[key] = bool(row[key])
    return {**me, **row, 'is_admin': me['username'] in admins(), 'email_available': email_available()}


def social_allowed(c, *ids):
    for identifier in ids:
        row = c.execute('SELECT private_library OR banned FROM profiles WHERE user_id=?',(identifier,)).fetchone()
        if not row or row[0]: return False
    return True


def rate_limit(db, key, limit, seconds):
    now = int(time.time())
    blocked = False
    with db() as c:
        c.execute('DELETE FROM rate_limits WHERE expires<=?', (now,))
        c.execute('DELETE FROM abuse_events WHERE created<?', (now-30*86400,))
        hashed = hashlib.sha256(key.encode()).hexdigest()
        c.execute('INSERT INTO rate_limits VALUES(?,1,?) ON CONFLICT(key) DO UPDATE SET hits=hits+1', (hashed,now+seconds))
        hits = c.execute('SELECT hits FROM rate_limits WHERE key=?',(hashed,)).fetchone()[0]
        if hits > limit:
            blocked = True
            if hits == limit+1:
                c.execute('INSERT INTO abuse_events(created,reason,actor) VALUES(?,?,?)',(now,'Rate limit: '+key.split(':')[0],hashed[:16]))
    if blocked: fail(429, 'Too many attempts. Please wait before trying again.')


def email_available():
    return bool(os.getenv('SMTP_HOST') and os.getenv('SMTP_FROM'))


def enqueue_email(c, user_id, address, subject, body, kind):
    c.execute('INSERT INTO email_outbox(id,user_id,address,subject,body,kind,next_attempt) VALUES(?,?,?,?,?,?,?)',
              (secrets.token_hex(16),user_id,address,subject,body,kind,int(time.time())))


def notify_trade(c, recipient):
    p = c.execute('SELECT * FROM profiles WHERE user_id=?',(recipient,)).fetchone()
    if email_available() and p and p['email_verified'] and p['email_notifications'] and not p['banned'] and not p['private_library']:
        # Do not put untrusted user text or private book details into email.
        enqueue_email(c,recipient,p['email'],'New BookBridge trade request','A friend requested a book swap. Open your BookBridge app and check the Trades tab.','trade')


def deliver_email(job):
    message = EmailMessage()
    message['From'] = os.environ['SMTP_FROM']
    message['To'] = job['address']
    message['Subject'] = job['subject']
    message.set_content(job['body'])
    host = os.environ['SMTP_HOST']
    use_ssl = os.getenv('SMTP_SSL','false').lower() == 'true'
    port = int(os.getenv('SMTP_PORT','465' if use_ssl else '587'))
    context = ssl.create_default_context()
    conn = smtplib.SMTP_SSL(host,port,timeout=15,context=context) if use_ssl else smtplib.SMTP(host,port,timeout=15)
    with conn as smtp:
        if not use_ssl: smtp.starttls(context=context)
        if os.getenv('SMTP_USER'): smtp.login(os.environ['SMTP_USER'], os.environ.get('SMTP_PASSWORD',''))
        smtp.send_message(message)


def send_next_email(db):
    now = int(time.time())
    with db() as c:
        c.execute("DELETE FROM email_outbox WHERE status<>'pending' AND next_attempt<?",(now-7*86400,))
        row = c.execute("SELECT * FROM email_outbox WHERE status='pending' AND next_attempt<=? ORDER BY next_attempt LIMIT 1",(now,)).fetchone()
        if not row: return
        job = dict(row)
        p = c.execute('SELECT * FROM profiles WHERE user_id=?',(job['user_id'],)).fetchone()
        code = c.execute('SELECT expires FROM email_codes WHERE user_id=?',(job['user_id'],)).fetchone()
        allowed = p and not p['banned'] and p['email']==job['address']
        if job['kind']=='trade': allowed = allowed and p['email_verified'] and p['email_notifications'] and not p['private_library']
        else: allowed = allowed and code and code['expires']>now
        if not allowed:
            c.execute("UPDATE email_outbox SET status='cancelled',body='',address='' WHERE id=?",(job['id'],))
            return
    try:
        deliver_email(job)
        status = 'sent'
    except (OSError, smtplib.SMTPException, ValueError):
        status = 'failed' if job['attempts']>=4 else 'pending'
    with db() as c:
        c.execute('UPDATE email_outbox SET status=?,attempts=attempts+1,next_attempt=?,body=CASE WHEN ?=\'pending\' THEN body ELSE \'\' END,address=CASE WHEN ?=\'pending\' THEN address ELSE \'\' END WHERE id=?',
                  (status,now+min(3600,60*2**job['attempts']),status,status,job['id']))


async def email_loop(db):
    while True:
        if email_available(): await asyncio.to_thread(send_next_email, db)
        await asyncio.sleep(10)


class Settings(BaseModel):
    display_name: str = Field(default='', max_length=80)
    town: str = Field(default='', max_length=100)
    discoverable: bool = False
    private_library: bool = False
    secondary_review: bool = True
    review_mode: Literal['cleanup','lookup'] = 'cleanup'
    email: str = Field(default='',max_length=254)
    email_notifications: bool = False

    @field_validator('display_name','town','email')
    @classmethod
    def trim(cls,v): return v.strip()

    @field_validator('email')
    @classmethod
    def email_format(cls,v):
        if v and not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+',v): raise ValueError('Enter a valid email address.')
        return v


class Reading(BaseModel):
    pages_read: int = Field(default=0,ge=0,le=100000)
    review: str = Field(default='',max_length=5000)
    rating: int | None = Field(default=None,ge=1,le=5)
    finished: bool = False


class Verification(BaseModel):
    code: str = Field(pattern=r'^\d{6}$')


class Ban(BaseModel):
    banned: bool


class BulkSave(BaseModel):
    acknowledge: bool = False


class LibraryInput(BaseModel):
    name: str = Field(min_length=1,max_length=100)
    @field_validator('name')
    @classmethod
    def trim(cls,v):
        if not v.strip(): raise ValueError('A library name is required.')
        return v.strip()

class MemberInput(BaseModel):
    username: str = Field(pattern=r'^[a-zA-Z0-9_]{3,32}$')


def library_access(c, library_id, user_id, manage=False):
    row = c.execute('SELECT * FROM libraries WHERE id=?',(library_id,)).fetchone()
    if not row or not c.execute('SELECT 1 FROM library_members WHERE library_id=? AND user_id=?',(library_id,user_id)).fetchone():
        fail(404,'Library not found or access removed.')
    if manage and row['owner'] != user_id: fail(403,'Only the library manager can change membership.')
    return row


def can_scan(c, row, user_id):
    if row['library_id']:
        return bool(c.execute('SELECT 1 FROM library_members WHERE library_id=? AND user_id=?',(row['library_id'],user_id)).fetchone())
    return row['owner']==user_id


def book_access(c,row,me,personal_access):
    if row['library_id']: library_access(c,row['library_id'],me['id'])
    else: personal_access(c,row['owner'],me)


def book_edit(c,row,me):
    if row['library_id']:
        library = library_access(c,row['library_id'],me['id'])
        if library['owner']==me['id']: return
    if row['owner'] != me['id']: fail(404,'Book not found.')


def install(app, m):
    db, user = m.db, m.user

    def admin(me=Depends(user)):
        if me['username'] not in admins(): fail(403,'Administrator access required.')
        return me

    @app.middleware('http')
    async def mutation_limit(request: Request, call_next):
        if request.method in ('POST','PATCH','PUT','DELETE') and not request.url.path.startswith('/auth/'):
            actor = request.headers.get('authorization') or (request.client.host if request.client else 'unknown')
            try:
                await asyncio.to_thread(rate_limit,db,'writes:'+actor,120,60)
            except HTTPException as exc:
                from fastapi.responses import JSONResponse
                return JSONResponse({'detail':exc.detail},status_code=exc.status_code,headers={'Retry-After':'60'})
        return await call_next(request)

    @app.patch('/me/settings')
    def settings(body: Settings, me=Depends(user)):
        with db() as c:
            old = profile_for(c,me)
            verified = old['email_verified'] and old['email']==body.email
            if old['email'] != body.email:
                c.execute('DELETE FROM email_codes WHERE user_id=?',(me['id'],))
                c.execute("DELETE FROM email_outbox WHERE user_id=? AND status='pending'",(me['id'],))
            c.execute('UPDATE profiles SET display_name=?,town=?,discoverable=?,private_library=?,secondary_review=?,review_mode=?,email=?,email_verified=?,email_notifications=? WHERE user_id=?',
                      (body.display_name,body.town,body.discoverable and not body.private_library,body.private_library,body.secondary_review,body.review_mode,body.email,verified,body.email_notifications,me['id']))
            if body.private_library:
                c.execute('DELETE FROM invites WHERE user_id=?',(me['id'],))
                c.execute("UPDATE trades SET status='cancelled' WHERE (sender=? OR recipient=?) AND status IN ('pending','accepted')",(me['id'],me['id']))
            if not body.discoverable or body.private_library:
                c.execute('DELETE FROM friend_requests WHERE sender=? OR recipient=?',(me['id'],me['id']))
            return profile_for(c,me)

    @app.post('/me/email/send-code')
    def send_code(me=Depends(user)):
        if not email_available(): fail(503,'The server owner must configure SMTP before email can be sent.')
        rate_limit(db,'email:'+me['id'],3,3600)
        with db() as c:
            p = profile_for(c,me)
            if not p['email']: fail(422,'Save an email address in Settings first.')
            code = f'{secrets.randbelow(1000000):06d}'
            c.execute('INSERT OR REPLACE INTO email_codes VALUES(?,?,?,?)',(me['id'],m.digest(code),p['email'],m.now()+900))
            c.execute("DELETE FROM email_outbox WHERE user_id=? AND kind='verify'",(me['id'],))
            enqueue_email(c,me['id'],p['email'],'Verify your BookBridge email','Your verification code is '+code+'. It expires in 15 minutes. If you did not request this, ignore this email.','verify')
        return {'status':'queued'}

    @app.post('/me/email/verify')
    def verify(body: Verification, me=Depends(user)):
        rate_limit(db,'verify:'+me['id'],10,900)
        with db() as c:
            row = c.execute('SELECT * FROM email_codes WHERE user_id=? AND expires>?',(me['id'],m.now())).fetchone()
            if not row or not secrets.compare_digest(row['code_hash'],m.digest(body.code)): fail(400,'Incorrect or expired code.')
            c.execute('UPDATE profiles SET email_verified=1 WHERE user_id=? AND email=?',(me['id'],row['email']))
            c.execute('DELETE FROM email_codes WHERE user_id=?',(me['id'],))
        return {'verified':True}

    @app.get('/people/suggestions')
    def suggestions(me=Depends(user)):
        with db() as c:
            own = profile_for(c,me)
            if not own['discoverable'] or own['private_library']: return []
            # Newest friendships receive a small extra weight; no names of mutual friends are exposed.
            edges = c.execute('SELECT rowid,a,b FROM friends WHERE a=? OR b=? ORDER BY rowid DESC',(me['id'],me['id'])).fetchall()
            mine = {r['b'] if r['a']==me['id'] else r['a'] for r in edges}
            recent = {r['b'] if r['a']==me['id'] else r['a'] for r in edges[:5]}
            results = []
            for row in c.execute('SELECT u.id,u.username,p.display_name,p.town FROM users u JOIN profiles p ON p.user_id=u.id WHERE p.discoverable=1 AND p.private_library=0 AND p.banned=0 AND u.id<>?',(me['id'],)).fetchall():
                if row['id'] in mine: continue
                if c.execute('SELECT 1 FROM friend_requests WHERE (sender=? AND recipient=?) OR (recipient=? AND sender=?)',(me['id'],row['id'],me['id'],row['id'])).fetchone(): continue
                theirs = {r['b'] if r['a']==row['id'] else r['a'] for r in c.execute('SELECT a,b FROM friends WHERE a=? OR b=?',(row['id'],row['id']))}
                mutual = mine & theirs
                nearby = bool(own['town'] and own['town'].casefold()==row['town'].casefold())
                if not mutual and not nearby: continue
                results.append({'id':row['id'],'username':row['username'],'display_name':row['display_name'],'mutual_friends':len(mutual),'same_town':nearby,'score':len(mutual)*3+len(recent & theirs)+int(nearby)*2})
            return [{k:v for k,v in r.items() if k!='score'} for r in sorted(results,key=lambda r:(-r['score'],r['username']))[:30]]

    @app.get('/people/requests')
    def requests(me=Depends(user)):
        with db() as c:
            return [dict(r) for r in c.execute('SELECT f.sender,f.recipient,f.created,u.username,p.display_name FROM friend_requests f JOIN users u ON u.id=CASE WHEN f.sender=? THEN f.recipient ELSE f.sender END JOIN profiles p ON p.user_id=u.id WHERE (f.sender=? OR f.recipient=?) AND p.banned=0 AND p.private_library=0',(me['id'],)*3)]

    @app.post('/people/{person_id}/request',status_code=201)
    def request_friend(person_id: str, me=Depends(user)):
        rate_limit(db,'friendrequests:'+me['id'],20,3600)
        with db() as c:
            target = c.execute('SELECT * FROM profiles WHERE user_id=?',(person_id,)).fetchone()
            own = profile_for(c,me)
            if not own['discoverable'] or own['private_library']: fail(403,'Enable friend discovery in Settings first.')
            if not target or not target['discoverable'] or target['private_library'] or target['banned']: fail(404,'Person unavailable.')
            if person_id==me['id'] or m.friends(c,person_id,me['id']): fail(409,'Already connected.')
            if c.execute('SELECT 1 FROM friend_requests WHERE sender=? AND recipient=?',(person_id,me['id'])).fetchone(): fail(409,'They already sent a request. Accept it in Friends.')
            c.execute('INSERT OR IGNORE INTO friend_requests VALUES(?,?,?)',(me['id'],person_id,m.now()))
        return {'status':'pending'}

    @app.post('/people/{person_id}/accept')
    def accept(person_id: str, me=Depends(user)):
        with db() as c:
            row = c.execute('SELECT 1 FROM friend_requests WHERE sender=? AND recipient=?',(person_id,me['id'])).fetchone()
            if not row or not social_allowed(c,me['id'],person_id): fail(404,'Request unavailable.')
            c.execute('INSERT OR IGNORE INTO friends VALUES(?,?)',tuple(sorted([me['id'],person_id])))
            c.execute('DELETE FROM friend_requests WHERE (sender=? AND recipient=?) OR (sender=? AND recipient=?)',(person_id,me['id'],me['id'],person_id))
        return {'status':'accepted'}

    @app.delete('/people/{person_id}/request',status_code=204)
    def decline(person_id: str, me=Depends(user)):
        with db() as c:
            c.execute('DELETE FROM friend_requests WHERE (sender=? AND recipient=?) OR (sender=? AND recipient=?)',(person_id,me['id'],me['id'],person_id))

    @app.post('/queue/accept-ready')
    def accept_ready(body: BulkSave, me=Depends(user)):
        if not body.acknowledge: fail(422,'Acknowledge that AI results may be wrong before saving without review.')
        with db() as c:
            rows = [dict(r) for r in c.execute("SELECT * FROM scans WHERE library_id IS NULL AND owner=? AND status='ready' AND expires>? ORDER BY seq LIMIT 500",(me['id'],m.now()))]
        saved, skipped = [], []
        for row in rows:
            try:
                fields = json.loads(row['metadata'])
                data = m.BookInput(**{**fields,'available':False})
                result = m.save(row['id'],data,me)
                saved.append(result['book_id'])
            except (HTTPException, ValueError) as exc:
                skipped.append({'scan_id':row['id'],'reason':getattr(exc,'detail',str(exc))})
        return {'saved':saved,'skipped':skipped}

    @app.get('/reading')
    def journal(me=Depends(user)):
        with db() as c:
            return [dict(r) for r in c.execute('SELECT * FROM reading_log WHERE user_id=? ORDER BY updated DESC',(me['id'],))]

    @app.put('/reading/{book_id}')
    def log_reading(book_id: str, body: Reading, me=Depends(user)):
        with db() as c:
            old = c.execute('SELECT * FROM reading_log WHERE user_id=? AND book_id=?',(me['id'],book_id)).fetchone()
            row = c.execute('SELECT * FROM books WHERE id=? AND owner=? AND removed=0',(book_id,me['id'])).fetchone()
            if not row and not old: fail(404,'Book not in your library or reading journal.')
            if row and row['library_id']: library_access(c,row['library_id'],me['id'])
            row = row or old
            c.execute('INSERT INTO reading_log VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id,book_id) DO UPDATE SET pages_read=excluded.pages_read,review=excluded.review,rating=excluded.rating,finished=excluded.finished,updated=excluded.updated',
                      (me['id'],book_id,row['title'],row['author'],row['isbn'],body.pages_read,body.review.strip(),body.rating,body.finished,m.now()))
        return {'saved':True}

    @app.get('/me/stats')
    def stats(me=Depends(user)):
        with db() as c:
            books = c.execute('SELECT title,author,isbn FROM books WHERE owner=? AND removed=0 AND library_id IS NULL',(me['id'],)).fetchall()
            unique = {r['isbn'] or (r['title'].casefold().strip(),r['author'].casefold().strip()) for r in books}
            reading = c.execute("SELECT COUNT(CASE WHEN trim(review)<>'' THEN 1 END) AS reviews,COALESCE(SUM(pages_read),0) AS pages_read,COALESCE(SUM(finished),0) AS finished FROM reading_log WHERE user_id=?",(me['id'],)).fetchone()
            trades = c.execute("SELECT COUNT(*) FROM trades WHERE status='completed' AND (sender=? OR recipient=?)",(me['id'],me['id'])).fetchone()[0]
            return {'books':len(books),'unique_books':len(unique),**dict(reading),'books_traded':trades,'books_received':trades}

    @app.get('/popular')
    def popular(me=Depends(user)):
        with db() as c:
            # Only opt-in shelves; require at least three distinct owners to reduce disclosure.
            rows = c.execute("SELECT b.title,b.author,COUNT(DISTINCT b.owner) AS owners FROM books b JOIN profiles p ON p.user_id=b.owner WHERE b.removed=0 AND b.library_id IS NULL AND p.discoverable=1 AND p.private_library=0 AND p.banned=0 GROUP BY lower(trim(b.title)),lower(trim(b.author)) HAVING COUNT(DISTINCT b.owner)>=3 ORDER BY owners DESC,b.title LIMIT 10").fetchall()
            return [dict(r) for r in rows]

    @app.get('/admin/stats')
    def admin_stats(me=Depends(admin)):
        with db() as c:
            return {'users':c.execute('SELECT COUNT(*) FROM users').fetchone()[0], 'banned':c.execute('SELECT COUNT(*) FROM profiles WHERE banned=1').fetchone()[0], 'books':c.execute('SELECT COUNT(*) FROM books WHERE removed=0').fetchone()[0], 'queued_scans':c.execute("SELECT COUNT(*) FROM scans WHERE status IN ('queued','identifying','enriching')").fetchone()[0], 'completed_trades':c.execute("SELECT COUNT(*) FROM trades WHERE status='completed'").fetchone()[0], 'abuse_flags_24h':c.execute('SELECT COUNT(*) FROM abuse_events WHERE created>?',(m.now()-86400,)).fetchone()[0], 'email_failures':c.execute("SELECT COUNT(*) FROM email_outbox WHERE status='failed'").fetchone()[0], 'database_mb':round((m.DATA/'bookbridge.sqlite3').stat().st_size/1024**2,2)}

    @app.get('/admin/users')
    def admin_users(q: str = '', me=Depends(admin)):
        with db() as c:
            return [dict(r) for r in c.execute('SELECT u.id,u.username,p.display_name,p.banned FROM users u JOIN profiles p ON p.user_id=u.id WHERE instr(lower(u.username),lower(?))>0 ORDER BY u.username LIMIT 100',(q[:100],))]

    @app.patch('/admin/users/{user_id}')
    def ban(user_id: str, body: Ban, me=Depends(admin)):
        with db() as c:
            target = c.execute('SELECT * FROM users WHERE id=?',(user_id,)).fetchone()
            if not target: fail(404,'User not found.')
            if target['username'] in admins(): fail(409,'Remove this account from BOOKBRIDGE_ADMINS before banning it.')
            c.execute('UPDATE profiles SET banned=? WHERE user_id=?',(body.banned,user_id))
            if body.banned:
                c.execute('DELETE FROM sessions WHERE user_id=?',(user_id,))
                c.execute('DELETE FROM invites WHERE user_id=?',(user_id,))
                c.execute('DELETE FROM friend_requests WHERE sender=? OR recipient=?',(user_id,user_id))
                c.execute('DELETE FROM scans WHERE owner=?',(user_id,))
                c.execute("UPDATE trades SET status='cancelled' WHERE (sender=? OR recipient=?) AND status IN ('pending','accepted')",(user_id,user_id))
            c.execute('INSERT INTO admin_audit(created,admin,action,target) VALUES(?,?,?,?)',(m.now(),me['id'],'ban' if body.banned else 'unban',user_id))
        return {'banned':body.banned}

    @app.get('/admin/books')
    def admin_books(q: str = '', me=Depends(admin)):
        with db() as c:
            return [dict(r) for r in c.execute('SELECT b.id,b.title,b.author,u.username FROM books b JOIN users u ON u.id=b.owner WHERE b.removed=0 AND (instr(lower(b.title),lower(?))>0 OR b.id=?) ORDER BY b.created DESC LIMIT 100',(q[:500],q[:500]))]

    @app.delete('/admin/books/{book_id}',status_code=204)
    def remove_book(book_id: str, me=Depends(admin)):
        with db() as c:
            m.book(c,book_id)
            c.execute('UPDATE books SET removed=1,available=0 WHERE id=?',(book_id,))
            c.execute('DELETE FROM book_images WHERE book_id=?',(book_id,))
            c.execute("UPDATE trades SET status='cancelled' WHERE (wanted=? OR offered=?) AND status IN ('pending','accepted')",(book_id,book_id))
            c.execute('INSERT INTO admin_audit(created,admin,action,target) VALUES(?,?,?,?)',(m.now(),me['id'],'remove_book',book_id))

    @app.get('/admin/events')
    def events(me=Depends(admin)):
        with db() as c:
            return {'abuse':[dict(r) for r in c.execute('SELECT created,reason,actor FROM abuse_events ORDER BY id DESC LIMIT 50')], 'actions':[dict(r) for r in c.execute('SELECT created,action,target FROM admin_audit ORDER BY id DESC LIMIT 50')]}

    @app.get('/libraries')
    def libraries(me=Depends(user)):
        with db() as c:
            return [dict(r) for r in c.execute('SELECT l.*,COUNT(DISTINCT b.id) AS books FROM libraries l JOIN library_members lm ON lm.library_id=l.id AND lm.user_id=? LEFT JOIN books b ON b.library_id=l.id AND b.removed=0 GROUP BY l.id ORDER BY l.name',(me['id'],))]

    @app.post('/libraries',status_code=201)
    def create_library(body: LibraryInput, me=Depends(admin)):
        with db() as c:
            identifier = m.uid()
            c.execute('INSERT INTO libraries VALUES(?,?,?,?)',(identifier,body.name,me['id'],m.now()))
            c.execute('INSERT INTO library_members VALUES(?,?)',(identifier,me['id']))
        return {'id':identifier,'name':body.name}

    @app.get('/libraries/{library_id}/members')
    def members(library_id: str, me=Depends(user)):
        with db() as c:
            library_access(c,library_id,me['id'],manage=True)
            return [dict(r) for r in c.execute('SELECT u.id,u.username,p.display_name FROM library_members lm JOIN users u ON u.id=lm.user_id JOIN profiles p ON p.user_id=u.id WHERE lm.library_id=? ORDER BY u.username',(library_id,))]

    @app.post('/libraries/{library_id}/members',status_code=201)
    def add_member(library_id: str, body: MemberInput, me=Depends(user)):
        with db() as c:
            library_access(c,library_id,me['id'],manage=True)
            row = c.execute('SELECT u.id FROM users u JOIN profiles p ON p.user_id=u.id WHERE u.username=? AND p.banned=0',(body.username.lower(),)).fetchone()
            if not row: fail(404,'Account not found. Ask them to create an account first.')
            c.execute('INSERT OR IGNORE INTO library_members VALUES(?,?)',(library_id,row['id']))
        return {'added':True}

    @app.delete('/libraries/{library_id}/members/{user_id}',status_code=204)
    def remove_member(library_id: str, user_id: str, me=Depends(user)):
        with db() as c:
            library = library_access(c,library_id,me['id'],manage=True)
            if library['owner']==user_id: fail(409,'The library manager must remain a member.')
            c.execute('DELETE FROM library_members WHERE library_id=? AND user_id=?',(library_id,user_id))

    @app.post('/libraries/{library_id}/accept-ready')
    def accept_library_ready(library_id: str, body: BulkSave, me=Depends(user)):
        if not body.acknowledge: fail(422,'Acknowledge that AI results may be wrong.')
        with db() as c:
            library_access(c,library_id,me['id'])
            rows = [dict(r) for r in c.execute("SELECT * FROM scans WHERE library_id=? AND status='ready' AND expires>? ORDER BY seq LIMIT 500",(library_id,m.now()))]
        saved,skipped = [],[]
        for row in rows:
            try:
                saved.append(m.save(row['id'],m.BookInput(**json.loads(row['metadata'])),me)['book_id'])
            except (HTTPException,ValueError) as exc:
                skipped.append({'scan_id':row['id'],'reason':getattr(exc,'detail',str(exc))})
        return {'saved':saved,'skipped':skipped}
