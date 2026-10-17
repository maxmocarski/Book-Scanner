import json
import re
import threading
import asyncio
from test_backend import client, account, add, connect, enqueue, process, jpeg
from api import main, community, mobile


def test_profile_setup_persists_and_partial_settings_preserve_it(client):
    c=client;_,a=account(c,'alice')
    assert not c.get('/me',headers=a).json()['profile_complete']
    assert c.post('/me/profile-setup',headers=a,json={'first_name':' ','last_name':'Reader'}).status_code==422
    p=c.post('/me/profile-setup',headers=a,json={'first_name':'Alice','last_name':'Reader','town':'Fairfield, CT'}).json()
    assert p['profile_complete'] and p['display_name']=='Alice Reader'
    assert c.patch('/me/settings',headers=a,json={'secondary_review':False}).status_code==200
    c.post('/auth/logout',headers=a)
    login=c.post('/auth/login',json={'username':'alice','password':'my-testing-password'}).json()
    p=c.get('/me',headers={'Authorization':'Bearer '+login['access_token']}).json()
    assert p['town']=='Fairfield, CT' and p['first_name']=='Alice' and p['last_name']=='Reader'
    assert not p['secondary_review']
    mobile.initialize(main.db)
    assert c.get('/me',headers={'Authorization':'Bearer '+login['access_token']}).json()['profile_complete']


def test_duplicates_scope_editions_and_bulk(client):
    c=client;_,a=account(c,'alice');_,b=account(c,'bob')
    add(c,b)
    s=enqueue(c,a);process(c)
    assert c.get(s['status_url'],headers=a).json()['duplicate'] is None
    add(c,a);other=enqueue(c,a);process(c)
    duplicate=c.get(s['status_url'],headers=a).json()['duplicate']
    assert duplicate=={'saved_copies':1,'ready_copies':1,'edition_known':True}
    result=c.post('/queue/accept-ready',headers=a,json={'acknowledge':True}).json()
    assert len(result['saved'])==2
    books=c.get('/books',headers=a).json()
    assert len(books)==3 and len({x['edition_key'] for x in books})==1
    b0=books[0]
    c.patch('/books/'+b0['id'],headers=a,json={'title':b0['title'],'author':b0['author'],'isbn':'9780306406157'})
    assert len({b['edition_key'] for b in c.get('/books',headers=a).json()})==2
    assert mobile.edition_key({'title':'Book','author':'Author','isbn':'0306406152'})==mobile.edition_key({'title':'Book','author':'Author','isbn':'9780306406157'})
    assert mobile.edition_key({'title':'Book','author':'Author','isbn':None})!=mobile.edition_key({'title':'Book','author':'Author','isbn':'9780306406157'})


def test_admin_reset_single_use_expiry_and_session_revocation(client,monkeypatch):
    c=client;monkeypatch.setenv('BOOKBRIDGE_ADMINS','manager');_,admin=account(c,'manager');aid,a=account(c,'alice');_,b=account(c,'bob')
    assert c.post('/admin/users/'+aid+'/reset-code',headers=b).status_code==403
    result=c.post('/admin/users/'+aid+'/reset-code',headers=admin)
    assert result.headers['cache-control']=='no-store'
    code=result.json()['code']
    with main.db() as db:
        row=db.execute('SELECT * FROM password_resets WHERE user_id=?',(aid,)).fetchone()
        assert row['token_hash']!=code
    assert c.post('/auth/reset-password',json={'username':'bob','code':code,'password':'newpassword'}).status_code==400
    assert c.post('/auth/reset-password',json={'username':'alice','code':code,'password':'newpassword'}).status_code==200
    assert c.get('/me',headers=a).status_code==401
    assert c.post('/auth/login',json={'username':'alice','password':'my-testing-password'}).status_code==401
    assert c.post('/auth/login',json={'username':'alice','password':'newpassword'}).status_code==200
    assert c.post('/auth/reset-password',json={'username':'alice','code':code,'password':'anotherpass'}).status_code==400
    code=c.post('/admin/users/'+aid+'/reset-code',headers=admin).json()['code']
    with main.db() as db:db.execute('UPDATE password_resets SET expires=0')
    assert c.post('/auth/reset-password',json={'username':'alice','code':code,'password':'anotherpass'}).status_code==400


def test_email_reset_generic_and_verification_gate(client,monkeypatch):
    c=client;aid,a=account(c,'alice')
    monkeypatch.setenv('SMTP_HOST','smtp.invalid');monkeypatch.setenv('SMTP_FROM','books@example.org')
    sent=[];monkeypatch.setattr(community,'deliver_email',lambda job:sent.append(job))
    c.patch('/me/settings',headers=a,json={'email':'alice@example.org'})
    generic=c.post('/auth/forgot-password',json={'username':'alice'}).json()
    assert generic==c.post('/auth/forgot-password',json={'username':'unknown'}).json()
    with main.db() as db:assert db.execute('SELECT COUNT(*) FROM password_resets').fetchone()[0]==0
    c.post('/me/email/send-code',headers=a);community.send_next_email(main.db)
    code=re.search(r'\b\d{6}\b',sent[-1]['body']).group()
    c.post('/me/email/verify',headers=a,json={'code':code})
    c.post('/auth/forgot-password',json={'username':'alice'});community.send_next_email(main.db)
    assert sent[-1]['kind']=='reset'
    code=re.search(r'code is: (\S+)',sent[-1]['body']).group(1)
    assert c.post('/auth/reset-password',json={'username':'alice','code':code,'password':'differentpassword'}).status_code==200


def test_email_change_invalidates_reset_and_banned_account_cannot_reset(client,monkeypatch):
    c=client;monkeypatch.setenv('BOOKBRIDGE_ADMINS','manager');_,m=account(c,'manager');aid,a=account(c,'alice')
    with main.db() as db:
        db.execute("UPDATE profiles SET email='a@example.org',email_verified=1 WHERE user_id=?",(aid,))
        db.execute('INSERT INTO password_resets VALUES(?,?,?,?,?)',(aid,main.digest('long-code-for-testing'),main.now()+1000,'a@example.org','email'))
    c.patch('/me/settings',headers=a,json={'email':'b@example.org'})
    assert c.post('/auth/reset-password',json={'username':'alice','code':'long-code-for-testing','password':'newpassword'}).status_code==400
    code=c.post('/admin/users/'+aid+'/reset-code',headers=m).json()['code']
    c.patch('/admin/users/'+aid,headers=m,json={'banned':True})
    assert c.post('/auth/reset-password',json={'username':'alice','code':code,'password':'newpassword'}).status_code==400


def test_library_delete_purges_all_children_not_personal_books(client,monkeypatch):
    c=client;monkeypatch.setenv('BOOKBRIDGE_ADMINS','manager,otheradmin');_,m=account(c,'manager');_,other=account(c,'otheradmin');aid,a=account(c,'alice')
    personal=add(c,a)
    lib=c.post('/libraries',headers=m,json={'name':'School'}).json()['id']
    c.post('/libraries/'+lib+'/members',headers=m,json={'username':'alice'})
    def queue():return c.post('/scans',headers=a,data={'library_id':lib},files={'front':('a.jpg',jpeg(),'image/jpeg')}).json()
    first=queue();process(c)
    b=c.post(first['status_url']+'/save',headers=a,json={'title':'Library book','author':'Author'}).json()['book_id']
    c.put('/reading/'+b,headers=a,json={'pages_read':10})
    queued=queue()
    assert c.request('DELETE','/admin/libraries/'+lib,headers=a,json={'confirm_name':'School'}).status_code==403
    assert c.request('DELETE','/admin/libraries/'+lib,headers=m,json={'confirm_name':'wrong'}).status_code==422
    assert c.get('/libraries/'+lib+'/members',headers=other).status_code==200
    assert c.request('DELETE','/admin/libraries/'+lib,headers=other,json={'confirm_name':'School'}).status_code==204
    assert c.get('/books',headers=a).json()[0]['id']==personal
    assert c.get(queued['status_url'],headers=a).status_code==404
    with main.db() as db:
        for table in ('libraries','library_members','reading_log','scans','scan_images'):
            assert db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM books WHERE library_id IS NOT NULL').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM book_images WHERE book_id=?',(b,)).fetchone()[0]==0
        assert not db.execute('PRAGMA foreign_key_check').fetchall()


def test_library_delete_during_inference_does_not_resurrect_queue(client,monkeypatch):
    c=client;monkeypatch.setenv('BOOKBRIDGE_ADMINS','manager');_,m=account(c,'manager')
    lib=c.post('/libraries',headers=m,json={'name':'Town'}).json()['id']
    scan=c.post('/scans',headers=m,data={'library_id':lib},files={'front':('b.jpg',jpeg(),'image/jpeg')}).json()
    gate=asyncio.Event();started=threading.Event()
    async def identify(self,images):
        started.set();await gate.wait();return main.Metadata(title='Title',author='Author')
    monkeypatch.setattr(main.Scanner,'identify',identify)
    future=c.portal.start_task_soon(main.app.state.scanner.process_next);assert started.wait(3)
    assert c.request('DELETE','/admin/libraries/'+lib,headers=m,json={'confirm_name':'Town'}).status_code==204
    c.portal.call(gate.set);future.result(timeout=3)
    assert c.get(scan['status_url'],headers=m).status_code==404
