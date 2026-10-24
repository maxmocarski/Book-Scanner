"""BookBridge: private physical-book catalog and friend-to-friend swaps."""
import asyncio
from contextlib import contextmanager, asynccontextmanager, suppress
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time
import sys
from api import community, mobile, public
from core import shelves, batch
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator
from starlette.datastructures import UploadFile as FormUploadFile
from core.scanning import Metadata, Mode, Scanner, ScanError, photo_bytes, valid_isbn
from api.schema import initialize
DATA = Path(os.getenv('BOOKBRIDGE_DATA', './data'))
@contextmanager
def db():
    DATA.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATA / 'bookbridge.sqlite3', timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    try:
        conn.execute('BEGIN IMMEDIATE')
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
@asynccontextmanager
async def lifespan(app):
    DATA.mkdir(parents=True, exist_ok=True)
    lockfile = (DATA / 'scanner.lock').open('a')
    try:
        try:
            fcntl.flock(lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            raise RuntimeError('Another BookBridge worker is using this data directory. Run one worker.') from e
        initialize(db)
        community.initialize(db)
        mobile.initialize(db)
        with db() as c: shelves.initialize(c)
        cleanup_expired()
        app.state.scanner = Scanner(db)
        tasks = [asyncio.create_task(expiry_loop()), asyncio.create_task(community.email_loop(db))]
        if getattr(app.state, 'worker_enabled', True):
            tasks.append(asyncio.create_task(app.state.scanner.run()))
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with suppress(asyncio.CancelledError):
                    await task
    finally:
        lockfile.close()
def cleanup_expired():
    with db() as c:
        for table in ('scans', 'sessions', 'invites'):
            c.execute(f'DELETE FROM {table} WHERE expires IS NOT NULL AND expires<=?', (int(time.time()),))
async def expiry_loop():
    while True:
        await asyncio.sleep(60)
        await asyncio.to_thread(cleanup_expired)
app = FastAPI(title='BookBridge', version='0.7.0', lifespan=lifespan,
              description='Private books, durable scan queue, up to three photos, Gemma + text enrichment, and friend swaps. Photos require Bearer authentication.')
STATIC = Path(__file__).parent.parent / 'static'
app.mount('/static', StaticFiles(directory=STATIC), name='static')
@app.get('/', include_in_schema=False)
def home():
    return FileResponse(STATIC / 'index.html', headers={'Cache-Control': 'no-cache'})
bearer = HTTPBearer()
def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()
def uid():
    return secrets.token_hex(16)
def now():
    return int(time.time())
def fail(code, message):
    raise HTTPException(code, message)
def user(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
    with db() as c:
        row = c.execute('SELECT u.id,u.username FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires>? AND NOT EXISTS (SELECT 1 FROM profiles p WHERE p.user_id=u.id AND p.banned=1)',
                        (digest(credentials.credentials), now())).fetchone()
    if not row:
        fail(401, 'Sign in again.')
    return dict(row)
class Credentials(BaseModel):
    username: str = Field(pattern=r'^[a-zA-Z0-9_]{3,32}$')
    password: str = Field(min_length=8, max_length=128)
    website: str = Field(default='',max_length=200)
class BookInput(Metadata):
    title: str = Field(min_length=1, max_length=500)
    author: str = Field(min_length=1, max_length=500)
    available: bool = False
    shelf: str | None = Field(default=None, max_length=100)
    @field_validator("shelf")
    @classmethod
    def clean_shelf(cls, value):
        return value.strip() if value is not None else None
    @field_validator('title', 'author')
    @classmethod
    def no_blank(cls, v):
        if not v.strip():
            raise ValueError('Cannot be blank')
        return v.strip()
class InviteInput(BaseModel):
    code: str = Field(min_length=20, max_length=100)
class TradeInput(BaseModel):
    wanted_book_id: str
    offered_book_id: str
def password_hash(password, salt):
    return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
def session(c, user_id):
    token = secrets.token_urlsafe(32)
    c.execute('INSERT INTO sessions VALUES(?,?,?)', (digest(token), user_id, now()+7*86400))
    return {'access_token': token, 'token_type': 'bearer', 'expires_in': 7*86400, 'user_id': user_id}
@app.post('/auth/register', status_code=201)
def register(body: Credentials, request: Request):
    community.rate_limit(db,'register:'+(request.client.host if request.client else 'unknown'),20,3600)
    if body.website:
        with db() as c:
            c.execute('INSERT INTO abuse_events(created,reason,actor) VALUES(?,?,?)',(now(),'Registration honeypot','anonymous'))
        fail(422,'Registration rejected.')
    salt = secrets.token_hex(16)
    ph = password_hash(body.password, salt)
    with db() as c:
        identifier = uid()
        try:
            c.execute('INSERT INTO users VALUES(?,?,?,?)', (identifier, body.username.lower(), salt, ph))
        except sqlite3.IntegrityError:
            fail(409, 'Username already taken.')
        c.execute('INSERT INTO profiles(user_id) VALUES(?)',(identifier,))
        return session(c, identifier)
@app.post('/auth/login')
def login(body: Credentials, request: Request):
    community.rate_limit(db,'login:'+body.username.lower(),20,300)
    community.rate_limit(db,'login-ip:'+(request.client.host if request.client else 'unknown'),100,300)
    with db() as c:
        row = c.execute('SELECT * FROM users WHERE username=?', (body.username.lower(),)).fetchone()
        salt = row['salt'] if row else '00'*16
        computed = password_hash(body.password, salt)
        if not row or not hmac.compare_digest(computed, row['password_hash']):
            fail(401, 'Incorrect username or password.')
        if c.execute('SELECT banned FROM profiles WHERE user_id=?',(row['id'],)).fetchone()[0]:
            fail(403,'This account has been suspended.')
        return session(c, row['id'])
@app.post('/auth/logout', status_code=204)
def logout(credentials: HTTPAuthorizationCredentials = Depends(bearer), me=Depends(user)):
    with db() as c:
        c.execute('DELETE FROM sessions WHERE token_hash=?', (digest(credentials.credentials),))
@app.get('/me')
def profile(me=Depends(user)):
    with db() as c:
        return community.profile_for(c,me)
def friends(c, a, b):
    return c.execute('SELECT 1 FROM friends WHERE a=? AND b=?', tuple(sorted([a,b]))).fetchone() is not None
def access(c, owner, me):
    if owner != me['id'] and (not community.social_allowed(c,owner,me['id']) or not friends(c, owner, me['id'])):
        fail(404, 'Not found.')
@app.post('/friends/invites', status_code=201)
def invite(me=Depends(user)):
    code = secrets.token_urlsafe(32)
    with db() as c:
        if not community.social_allowed(c,me['id']): fail(403,'Turn off home-library-only mode to invite friends.')
        c.execute('DELETE FROM invites WHERE expires<=?', (now(),))
        c.execute('INSERT INTO invites VALUES(?,?,?)', (digest(code), me['id'], now()+86400))
    return {'code': code, 'expires_in': 86400, 'note': 'Share privately with a person you know. One use.'}
@app.post('/friends/accept')
def accept_invite(body: InviteInput, me=Depends(user)):
    with db() as c:
        row = c.execute('SELECT * FROM invites WHERE code_hash=? AND expires>?', (digest(body.code), now())).fetchone()
        if not row:
            fail(404, 'Invitation invalid or expired.')
        if not community.social_allowed(c,me['id'],row['user_id']): fail(403,'This account is using home-library-only mode.')
        if row['user_id'] == me['id']:
            fail(400, 'Cannot accept your own invitation.')
        c.execute('INSERT OR IGNORE INTO friends VALUES(?,?)', tuple(sorted([me['id'],row['user_id']])))
        c.execute('DELETE FROM invites WHERE code_hash=?', (digest(body.code),))
    return {'friend_id': row['user_id']}
@app.get('/friends')
def list_friends(me=Depends(user)):
    with db() as c:
        return [dict(r) for r in c.execute('SELECT u.id,u.username,p.display_name,p.private_library FROM users u JOIN profiles p ON p.user_id=u.id WHERE p.banned=0 AND u.id IN (SELECT CASE WHEN a=? THEN b ELSE a END FROM friends WHERE a=? OR b=?)', (me['id'],)*3)]
@app.delete('/friends/{friend_id}', status_code=204)
def remove_friend(friend_id: str, me=Depends(user)):
    with db() as c:
        c.execute('DELETE FROM friends WHERE a=? AND b=?', tuple(sorted([me['id'],friend_id])))
        c.execute("UPDATE trades SET status='cancelled' WHERE status IN ('pending','accepted') AND ((sender=? AND recipient=?) OR (sender=? AND recipient=?))", (me['id'],friend_id,friend_id,me['id']))
def scan_row(c, identifier, owner):
    row = c.execute('SELECT * FROM scans WHERE id=? AND (expires IS NULL OR expires>?)', (identifier,int(time.time()))).fetchone()
    if not row or not community.can_scan(c,row,owner):
        fail(404, 'Scan not found or expired.')
    return row
def public_scan(c, row):
    identifier = row['id']
    position = None
    if row['status']=='queued':
        position = c.execute("SELECT COUNT(*) FROM scans WHERE status='queued' AND (queued_at<? OR (queued_at=? AND seq<=?))", (row['queued_at'],row['queued_at'],row['seq'])).fetchone()[0]
    result = {k:row[k] for k in ('id','status','enrichment_mode','created','expires','error','library_id','shelf','shelf_position','scan_mode','book_count','batch_id','batch_position')}
    result['shelf_label'] = shelves.label(row['shelf'],row['shelf_position'])
    if row['scan_mode']=='shelf' and row['status']=='ready':result['status']='expanded'
    result['child_scan_ids']=json.loads(row['batch_children'])
    result['scan_id'] = identifier
    result['queue_position'] = position
    result['status_url'] = '/scans/'+identifier
    for key in ('metadata','original_metadata','warnings','corrections','sources','lookup_suggestion'):
        result[key] = json.loads(row[key])
    result['duplicate'] = mobile.duplicate_info(c,row,result['metadata'])
    result['images'] = [{'position':r['position'],'view':r['view'],'url':f'/scans/{identifier}/images/{r["position"]}'} for r in c.execute('SELECT position,view FROM scan_images WHERE scan_id=? ORDER BY position',(identifier,))]
    return result
@app.post('/scans', status_code=202)
async def scan(request: Request, front: UploadFile | None = File(None), spine: UploadFile | None = File(None),
               back: UploadFile | None = File(None), enrichment: Mode | None = Form(None), library_id: str | None = Form(None), shelf: str = Form(default="", max_length=100), scan_mode: str = Form(default="single"), book_count: int = Form(default=1,ge=1,le=5),
               cover: UploadFile | None = File(None, description='Legacy name for front. Do not combine with front.'),
               details: UploadFile | None = File(None, description='Legacy name for back. Do not combine with back.'), me=Depends(user)):
    if scan_mode not in ('single','shelf'):fail(422,'Choose single-book or shelf mode.')
    library_id = library_id or None
    with db() as c:
        if library_id: community.library_access(c,library_id,me['id'])
        preferences = community.profile_for(c,me)
    form = await request.form()
    uploads = [(name,value) for name,value in form.multi_items() if isinstance(value,FormUploadFile)]
    if not 1 <= len(uploads) <= 3:
        fail(422, 'Attach one to three photos of one book: front, optional spine, optional back.')
    names = [name for name,value in uploads]
    if len(set(names)) != len(names) or any(name not in ('front','spine','back','cover','details') for name in names):
        fail(422, 'Each book view accepts one photo. Use front, spine and back.')
    if (front and cover) or (back and details):
        fail(422, 'Do not combine a legacy photo name with its replacement.')
    front = front or cover
    back = back or details
    if not front:
        fail(422, 'A front cover photo is required.')
    if scan_mode=='shelf' and (spine or back):fail(422,'Use one shelf photo with no more than 5 spines.')
    photos = []
    for view,upload in (('front',front),('spine',spine),('back',back)):
        if upload:
            raw = await upload.read(10*1024*1024+1)
            if len(raw)>10*1024*1024:
                fail(413,'Maximum photo size: 10 MB per image.')
            try:
                image = await asyncio.to_thread(photo_bytes,raw)
            except ScanError as e:
                fail(415,str(e))
            photos.append((view,image))
    scanner = app.state.scanner
    try:
        mode = enrichment or (preferences['review_mode'] if preferences['secondary_review'] else 'off')
        identifier = scanner.enqueue(me['id'],photos,mode,library_id=library_id,shelf=shelf.strip(),scan_mode=scan_mode,book_count=book_count)
    except ScanError as e:
        fail(429,str(e))
    with db() as c:
        return public_scan(c,scan_row(c,identifier,me['id']))
@app.get('/scans')
def list_scans(limit: int = 100, me=Depends(user)):
    if not 1 <= limit <= 500:
        fail(422,'limit must be between 1 and 500.')
    with db() as c:
        rows = c.execute("SELECT * FROM scans WHERE ((library_id IS NULL AND owner=?) OR library_id IN (SELECT library_id FROM library_members WHERE user_id=?)) AND (expires IS NULL OR expires>?) AND NOT (scan_mode='shelf' AND status='ready') ORDER BY seq DESC LIMIT ?", (me['id'],me['id'],now(),limit)).fetchall()
        return [public_scan(c,r) for r in rows]
@app.get('/scans/{scan_id}')
def scan_status(scan_id: str, me=Depends(user)):
    with db() as c:
        return public_scan(c,scan_row(c,scan_id,me['id']))
@app.get('/scans/{scan_id}/images/{position}')
def scan_photo(scan_id: str, position: int, me=Depends(user)):
    with db() as c:
        scan_row(c,scan_id,me['id'])
        row = c.execute('SELECT image FROM scan_images WHERE scan_id=? AND position=?',(scan_id,position)).fetchone()
        if not row:
            fail(404,'Image not found.')
        return Response(row['image'],media_type='image/jpeg',headers={'Cache-Control':'no-store'})
@app.post('/scans/{scan_id}/retry', status_code=202)
def retry_scan(scan_id: str, me=Depends(user)):
    scanner = app.state.scanner
    with db() as c:
        row = scan_row(c,scan_id,me['id'])
        if row['status'] != 'failed':
            fail(409,'Only failed scans can be retried.')
        pending = "status IN ('queued','identifying','enriching')"
        if c.execute('SELECT COALESCE(SUM(book_count),0) FROM scans WHERE '+pending).fetchone()[0]+row['book_count']>scanner.settings.max_pending or c.execute('SELECT COALESCE(SUM(book_count),0) FROM scans WHERE owner=? AND '+pending,(me['id'],)).fetchone()[0]+row['book_count']>scanner.settings.max_user_pending:
            fail(429,'Scan queue is full. Try again later.')
        c.execute("UPDATE scans SET status='queued',error=NULL,expires=NULL,queued_at=? WHERE id=?", (time.time(),scan_id))
        result = public_scan(c,scan_row(c,scan_id,me['id']))
    scanner.wake.set()
    return result
@app.post('/scans/{scan_id}/save', status_code=201)
def save(scan_id: str, body: BookInput, me=Depends(user)):
    try:
        isbn = valid_isbn(body.isbn)
    except ValueError as e:
        fail(422, str(e))
    with db() as c:
        row = scan_row(c,scan_id,me['id'])
        if row['scan_mode']=='shelf':fail(409,'Review and save the individual books from this shelf photo.')
        if row['status'] != 'ready':
            fail(409,'Wait until the scan is ready, then review before saving.')
        identifier = uid()
        audit = {k:json.loads(row[k]) for k in ('metadata','original_metadata','corrections','sources','lookup_suggestion')}
        shelf = row['shelf'] if body.shelf is None else body.shelf
        position = shelves.location(c,row,shelf)
        c.execute('INSERT INTO books(id,owner,title,author,isbn,available,created,scan_audit,library_id,shelf,shelf_position,added_order) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                  (identifier,row['owner'],body.title,body.author,isbn,int(body.available and not row['library_id']),now(),json.dumps(audit),row['library_id'],shelf,position,batch.next_order(c)))
        c.execute('INSERT INTO book_images SELECT ?,position,view,image FROM scan_images WHERE scan_id=?', (identifier,scan_id))
        c.execute('DELETE FROM scans WHERE id=?', (scan_id,))
    return {'book_id': identifier}
@app.delete('/scans/{scan_id}', status_code=204)
def discard(scan_id: str, me=Depends(user)):
    with db() as c:
        scan_row(c,scan_id,me['id'])
        c.execute('DELETE FROM scans WHERE id=?', (scan_id,))
def book(c, identifier):
    row = c.execute('SELECT * FROM books WHERE id=? AND removed=0', (identifier,)).fetchone()
    if not row:
        fail(404, 'Book not found.')
    return row
def locked(c, identifier):
    return c.execute("SELECT 1 FROM trades WHERE status='accepted' AND (wanted=? OR offered=?)", (identifier,identifier)).fetchone() is not None
def public_book(c, row):
    result = {k:row[k] for k in row.keys() if k != 'scan_audit'}
    result['edition_key'] = mobile.edition_key(row)
    result['shelf_label'] = shelves.label(row['shelf'],row['shelf_position'])
    result['scan_audit'] = json.loads(row['scan_audit'])
    result['images'] = [{'position':r['position'],'view':r['view'],'url':f'/books/{row["id"]}/images/{r["position"]}'} for r in c.execute('SELECT position,view FROM book_images WHERE book_id=? ORDER BY position',(row['id'],))]
    result['image_url'] = '/books/'+row['id']+'/image'
    return result
@app.get('/books')
def collection(owner_id: str | None = None, library_id: str | None = None, me=Depends(user)):
    owner = owner_id or me['id']
    with db() as c:
        if library_id:
            community.library_access(c,library_id,me['id'])
            return [public_book(c,r) for r in c.execute('SELECT * FROM books WHERE library_id=? AND removed=0 ORDER BY created DESC,id',(library_id,))]
        access(c,owner,me)
        return [public_book(c,r) for r in c.execute('SELECT * FROM books WHERE owner=? AND removed=0 AND library_id IS NULL ORDER BY created DESC,id', (owner,))]
@app.get('/books/{book_id}/image')
def photo(book_id: str, me=Depends(user)):
    return book_photo(book_id,0,me)
@app.get('/books/{book_id}/images/{position}')
def book_photo(book_id: str, position: int, me=Depends(user)):
    with db() as c:
        row = book(c,book_id)
        community.book_access(c,row,me,access)
        image = c.execute('SELECT image FROM book_images WHERE book_id=? AND position=?',(book_id,position)).fetchone()
        if not image:
            fail(404,'Image not found.')
        return Response(image['image'], media_type='image/jpeg', headers={'Cache-Control': 'no-store'})
@app.patch('/books/{book_id}')
def edit(book_id: str, body: BookInput, me=Depends(user)):
    try:
        isbn = valid_isbn(body.isbn)
    except ValueError as e:
        fail(422,str(e))
    with db() as c:
        row = book(c,book_id)
        community.book_edit(c,row,me)
        if locked(c,book_id):
            fail(409,'Cancel the accepted trade before editing.')
        shelf = row['shelf'] if body.shelf is None else body.shelf
        position = shelves.location(c,row,shelf)
        c.execute('UPDATE books SET title=?,author=?,isbn=?,available=?,shelf=?,shelf_position=? WHERE id=?', (body.title,body.author,isbn,int(body.available and not row['library_id']),shelf,position,book_id))
        c.execute("UPDATE trades SET status='cancelled' WHERE status='pending' AND (wanted=? OR offered=?)", (book_id,book_id))
        return public_book(c,book(c,book_id))
@app.delete('/books/{book_id}', status_code=204)
def delete_book(book_id: str, me=Depends(user)):
    with db() as c:
        community.book_edit(c,book(c,book_id),me)
        if c.execute('SELECT 1 FROM trades WHERE wanted=? OR offered=?', (book_id,book_id)).fetchone():
            fail(409,'Book has trade history. Set available=false to remove it from trading.')
        c.execute('UPDATE books SET removed=1,available=0 WHERE id=?',(book_id,))
        c.execute('DELETE FROM book_images WHERE book_id=?',(book_id,))
@app.post('/trades', status_code=201)
def propose(body: TradeInput, me=Depends(user)):
    with db() as c:
        wanted, offered = book(c,body.wanted_book_id), book(c,body.offered_book_id)
        if wanted['library_id'] or offered['library_id'] or not community.social_allowed(c,me['id'],wanted['owner']): fail(403,'Shared or private libraries cannot participate in swaps.')
        if offered['owner'] != me['id'] or wanted['owner'] == me['id'] or not friends(c,me['id'],wanted['owner']):
            fail(403,'Only swap your own book with a friend.')
        if not wanted['available'] or not offered['available'] or locked(c,wanted['id']) or locked(c,offered['id']):
            fail(409,'Both books must be available.')
        identifier = uid()
        c.execute('INSERT INTO trades(id,sender,recipient,wanted,offered,status,created) VALUES(?,?,?,?,?,?,?)', (identifier,me['id'],wanted['owner'],wanted['id'],offered['id'],'pending',now()))
        community.notify_trade(c,wanted['owner'])
    return {'trade_id': identifier, 'status': 'pending'}
@app.get('/trades')
def list_trades(me=Depends(user)):
    with db() as c:
        return [dict(r) for r in c.execute("""
            SELECT t.*, w.title AS wanted_title, o.title AS offered_title,
                   s.username AS sender_username, r.username AS recipient_username
            FROM trades t JOIN books w ON w.id=t.wanted JOIN books o ON o.id=t.offered
            JOIN users s ON s.id=t.sender JOIN users r ON r.id=t.recipient
            WHERE t.sender=? OR t.recipient=? ORDER BY t.created DESC
        """, (me['id'],)*2)]
def trade(c, identifier, me):
    row = c.execute('SELECT * FROM trades WHERE id=? AND (sender=? OR recipient=?)', (identifier,me['id'],me['id'])).fetchone()
    if not row:
        fail(404,'Trade not found.')
    return row
@app.post('/trades/{trade_id}/accept')
def accept_trade(trade_id: str, me=Depends(user)):
    with db() as c:
        t = trade(c,trade_id,me)
        if t['recipient'] != me['id']:
            fail(403,'Only the recipient can accept.')
        if t['status'] != 'pending':
            fail(409,'Trade is not pending.')
        wanted,offered = book(c,t['wanted']),book(c,t['offered'])
        if wanted['owner'] != t['recipient'] or offered['owner'] != t['sender'] or not friends(c,t['sender'],t['recipient']):
            fail(409,'Ownership or friendship changed.')
        if not wanted['available'] or not offered['available'] or locked(c,t['wanted']) or locked(c,t['offered']):
            fail(409,'A book is unavailable or reserved.')
        c.execute("UPDATE trades SET status='accepted' WHERE id=?", (trade_id,))
        c.execute("UPDATE trades SET status='cancelled' WHERE id<>? AND status='pending' AND (wanted IN (?,?) OR offered IN (?,?))", (trade_id,t['wanted'],t['offered'],t['wanted'],t['offered']))
    return {'status': 'accepted'}
@app.post('/trades/{trade_id}/cancel')
def cancel_trade(trade_id: str, me=Depends(user)):
    with db() as c:
        t = trade(c,trade_id,me)
        if t['status'] not in ('pending','accepted'):
            fail(409,'Trade already closed.')
        c.execute("UPDATE trades SET status='cancelled' WHERE id=?", (trade_id,))
    return {'status': 'cancelled'}
@app.post('/trades/{trade_id}/confirm-handoff')
def handoff(trade_id: str, me=Depends(user)):
    with db() as c:
        t = trade(c,trade_id,me)
        if t['status'] != 'accepted':
            fail(409,'Trade must be accepted first.')
        column = 'sender_confirm' if me['id']==t['sender'] else 'recipient_confirm'
        c.execute(f'UPDATE trades SET {column}=1 WHERE id=?', (trade_id,))
        t = trade(c,trade_id,me)
        if t['sender_confirm'] and t['recipient_confirm']:
            if book(c,t['wanted'])['owner'] != t['recipient'] or book(c,t['offered'])['owner'] != t['sender']:
                fail(409,'Ownership changed.')
            c.execute("UPDATE books SET owner=?,available=0,shelf='',shelf_position=NULL,added_order=? WHERE id=?", (t['sender'],batch.next_order(c),t['wanted']))
            c.execute("UPDATE books SET owner=?,available=0,shelf='',shelf_position=NULL,added_order=? WHERE id=?", (t['recipient'],batch.next_order(c),t['offered']))
            c.execute("UPDATE trades SET status='completed' WHERE id=?", (trade_id,))
        return dict(trade(c,trade_id,me))
@app.get('/health')
def health():
    return {'status': 'ok'}

community.install(app, sys.modules[__name__])

mobile.install(app, sys.modules[__name__])

public.install(app, sys.modules[__name__])

