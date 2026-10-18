"""Profile setup, password recovery, and explicit shared-library deletion."""
import secrets
from fastapi import Depends, Request
from pydantic import BaseModel, Field, field_validator
from api import community as cmt


def initialize(db):
    with db() as c:
        cols={r['name'] for r in c.execute('PRAGMA table_info(profiles)')}
        for name,definition in [('first_name',"TEXT NOT NULL DEFAULT ''"),('last_name',"TEXT NOT NULL DEFAULT ''"),('profile_complete','INTEGER NOT NULL DEFAULT 0')]:
            if name not in cols: c.execute(f'ALTER TABLE profiles ADD COLUMN {name} {definition}')
        c.execute('CREATE TABLE IF NOT EXISTS password_resets(user_id TEXT PRIMARY KEY REFERENCES users(id),token_hash TEXT NOT NULL,expires INTEGER NOT NULL,email TEXT,kind TEXT NOT NULL)')


def edition_key(row):
    """Known ISBNs never merge with unknown editions; ISBN-10/13 equivalents do."""
    isbn=(row['isbn'] or '').replace('-','').replace(' ','').upper()
    if isbn:
        if len(isbn)==10:
            stem='978'+isbn[:9]
            isbn=stem+str((-sum(int(n)*(1 if i%2==0 else 3) for i,n in enumerate(stem)))%10)
        return 'isbn:'+isbn
    normalize=lambda text:' '.join((text or '').casefold().split())
    return 'unknown:'+normalize(row['title'])+'|'+normalize(row['author'])


def duplicate_info(c,row,metadata):
    if row['status']!='ready' or not metadata.get('title') or not metadata.get('author'): return None
    key=edition_key({'isbn':metadata.get('isbn'),'title':metadata['title'],'author':metadata['author']})
    import json
    if row['library_id']:
        scope='library_id=?';args=(row['library_id'],)
    else:
        scope='library_id IS NULL AND owner=?';args=(row['owner'],)
    saved=sum(edition_key(b)==key for b in c.execute('SELECT title,author,isbn FROM books WHERE removed=0 AND '+scope,args))
    queued=0
    for other in c.execute("SELECT metadata FROM scans WHERE status='ready' AND id<>? AND expires>strftime('%s','now') AND "+scope,(row['id'],)+args):
        data=json.loads(other['metadata'])
        if data.get('title') and data.get('author') and edition_key({'title':data['title'],'author':data['author'],'isbn':data.get('isbn')})==key:queued+=1
    return {'saved_copies':saved,'ready_copies':queued,'edition_known':bool(metadata.get('isbn'))} if saved or queued else None


class ProfileSetup(BaseModel):
    first_name:str=Field(min_length=1,max_length=40)
    last_name:str=Field(min_length=1,max_length=40)
    town:str=Field(default='',max_length=100)
    @field_validator('first_name','last_name','town')
    @classmethod
    def clean(cls,v,info):
        v=v.strip()
        if info.field_name!='town' and not v:raise ValueError('Please enter your name.')
        return v

class RecoveryRequest(BaseModel):
    username:str=Field(pattern=r'^[a-zA-Z0-9_]{3,32}$')

class ResetPassword(RecoveryRequest):
    code:str=Field(min_length=16,max_length=128)
    password:str=Field(min_length=8,max_length=128)

class DeleteLibrary(BaseModel):
    confirm_name:str=Field(min_length=1,max_length=100)


def install(app,m):
    db=m.db
    def admin(me=Depends(m.user)):
        if me['username'] not in cmt.admins():m.fail(403,'Administrator access required.')
        return me

    def issue(c,user_id,kind,email=None):
        code=secrets.token_urlsafe(24)
        c.execute('INSERT OR REPLACE INTO password_resets VALUES(?,?,?,?,?)',(user_id,m.digest(code),m.now()+1800,email,kind))
        c.execute("DELETE FROM email_outbox WHERE user_id=? AND kind='reset'",(user_id,))
        return code

    @app.post('/me/profile-setup')
    def setup(body:ProfileSetup,me=Depends(m.user)):
        with db() as c:
            c.execute('UPDATE profiles SET first_name=?,last_name=?,display_name=?,town=?,profile_complete=1 WHERE user_id=?',(body.first_name,body.last_name,body.first_name+' '+body.last_name,body.town,me['id']))
            return cmt.profile_for(c,me)

    @app.post('/auth/forgot-password')
    def forgot(body:RecoveryRequest,request:Request):
        cmt.rate_limit(db,'recovery-ip:'+(request.client.host if request.client else 'unknown'),20,3600)
        cmt.rate_limit(db,'recovery-user:'+body.username.lower(),3,3600)
        with db() as c:
            row=c.execute('SELECT u.id,p.* FROM users u JOIN profiles p ON p.user_id=u.id WHERE u.username=?',(body.username.lower(),)).fetchone()
            if cmt.email_available() and row and row['email_verified'] and not row['banned']:
                code=issue(c,row['id'],'email',row['email'])
                cmt.enqueue_email(c,row['id'],row['email'],'Reset your BookBridge password','Your single-use reset code is: '+code+'\n\nOpen BookBridge, choose Forgot password, and enter your username, this code, and a new password. It expires in 30 minutes. Ignore this email if you did not request it.','reset')
        return {'message':'If this account has a verified email and email delivery is configured, a reset code will be sent. Otherwise, ask an administrator for a temporary code.'}

    @app.post('/auth/reset-password')
    def reset(body:ResetPassword,request:Request):
        cmt.rate_limit(db,'reset-ip:'+(request.client.host if request.client else 'unknown'),40,1800)
        cmt.rate_limit(db,'reset-user:'+body.username.lower(),10,1800)
        salt=secrets.token_hex(16)
        hashed=m.password_hash(body.password,salt)
        with db() as c:
            row=c.execute('SELECT u.id,r.*,p.banned,p.email AS current_email,p.email_verified FROM users u JOIN password_resets r ON r.user_id=u.id JOIN profiles p ON p.user_id=u.id WHERE u.username=?',(body.username.lower(),)).fetchone()
            if not row or row['banned'] or row['expires']<=m.now() or not secrets.compare_digest(row['token_hash'],m.digest(body.code.strip())):
                m.fail(400,'Invalid or expired reset code.')
            if row['kind']=='email' and (not row['email_verified'] or row['email']!=row['current_email']):m.fail(400,'Invalid or expired reset code.')
            c.execute('UPDATE users SET salt=?,password_hash=? WHERE id=?',(salt,hashed,row['id']))
            c.execute('DELETE FROM password_resets WHERE user_id=?',(row['id'],))
            c.execute('DELETE FROM sessions WHERE user_id=?',(row['id'],))
            c.execute("DELETE FROM email_outbox WHERE user_id=? AND kind='reset'",(row['id'],))
        return {'message':'Password changed. Sign in with your new password.'}

    @app.post('/admin/users/{user_id}/reset-code')
    def admin_reset(user_id:str,me=Depends(admin)):
        cmt.rate_limit(db,'admin-reset:'+me['id'],20,3600)
        with db() as c:
            row=c.execute('SELECT u.username,p.banned FROM users u JOIN profiles p ON p.user_id=u.id WHERE u.id=?',(user_id,)).fetchone()
            if not row:m.fail(404,'Account not found.')
            if row['banned']:m.fail(409,'Unban this account before issuing a reset code.')
            if row['username'] in cmt.admins():m.fail(403,'Administrator accounts must use verified email recovery or the server recovery command.')
            code=issue(c,user_id,'admin')
            c.execute('INSERT INTO admin_audit(created,admin,action,target) VALUES(?,?,?,?)',(m.now(),me['id'],'password_reset_code',user_id))
        return {'code':code,'expires_in':1800,'username':row['username']}

    @app.get('/admin/libraries')
    def all_libraries(me=Depends(admin)):
        with db() as c:
            return [dict(r) for r in c.execute('SELECT l.*,COUNT(DISTINCT b.id) AS books FROM libraries l LEFT JOIN books b ON b.library_id=l.id AND b.removed=0 GROUP BY l.id ORDER BY l.name')]

    @app.delete('/admin/libraries/{library_id}',status_code=204)
    def delete_library(library_id:str,body:DeleteLibrary,me=Depends(admin)):
        with db() as c:
            row=c.execute('SELECT name FROM libraries WHERE id=?',(library_id,)).fetchone()
            if not row:m.fail(404,'Library not found.')
            if body.confirm_name!=row['name']:m.fail(422,'Type the library name exactly to confirm deletion.')
            # Delete dependent records before their parents, in a single transaction.
            c.execute('DELETE FROM trades WHERE wanted IN (SELECT id FROM books WHERE library_id=?) OR offered IN (SELECT id FROM books WHERE library_id=?)',(library_id,library_id))
            c.execute('DELETE FROM reading_log WHERE book_id IN (SELECT id FROM books WHERE library_id=?)',(library_id,))
            c.execute('DELETE FROM books WHERE library_id=?',(library_id,))
            c.execute('DELETE FROM scans WHERE library_id=?',(library_id,))
            c.execute('DELETE FROM library_members WHERE library_id=?',(library_id,))
            c.execute('DELETE FROM libraries WHERE id=?',(library_id,))
            c.execute('DELETE FROM shelf_counters WHERE scope=?',('library:'+library_id,))
            c.execute('INSERT INTO admin_audit(created,admin,action,target) VALUES(?,?,?,?)',(m.now(),me['id'],'delete_library',library_id))
