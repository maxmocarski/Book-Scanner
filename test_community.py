import json
import time
import pytest
from test_backend import client, account, add, connect, enqueue, process, jpeg
from api import main, community


def settings(c,h,**changes):
    old=c.get('/me',headers=h).json()
    body={k:old[k] for k in community.Settings.model_fields}
    body.update(changes)
    r=c.patch('/me/settings',headers=h,json=body)
    assert r.status_code==200,r.text
    return r.json()


def test_password_profile_and_no_self_admin(client):
    c=client
    assert c.post('/auth/register',json={'username':'short','password':'1234567'}).status_code==422
    r=c.post('/auth/register',json={'username':'eight','password':'12345678'});assert r.status_code==201
    h={'Authorization':'Bearer '+r.json()['access_token']}
    p=settings(c,h,display_name='Reader Max',town='Fairfield, CT')
    assert p['display_name']=='Reader Max' and not p['discoverable'] and not p['is_admin']
    assert c.patch('/me/settings',headers=h,json={'is_admin':True}).json()['is_admin'] is False
    assert c.get('/admin/users',headers=h).status_code==403
    assert c.get('/books?owner_id=nonexistent',headers=h).status_code==404


def test_discovery_requests_and_private_library(client):
    c=client; aid,a=account(c,'alice');bid,b=account(c,'bob');_,other=account(c,'outsider')
    x=add(c,a);y=add(c,b)
    settings(c,a,discoverable=True,town='Fairfield, CT',display_name='Alice')
    settings(c,b,town='fairfield, ct')
    assert c.get('/people/suggestions',headers=a).json()==[]
    settings(c,b,discoverable=True)
    matches=c.get('/people/suggestions',headers=a).json()
    assert matches[0]['id']==bid and matches[0]['same_town'] and 'email' not in matches[0] and 'town' not in matches[0]
    assert c.post('/people/'+bid+'/request',headers=a).status_code==201
    assert c.get('/books?owner_id='+bid,headers=a).status_code==404
    assert c.post('/people/'+aid+'/accept',headers=other).status_code==404
    assert c.post('/people/'+aid+'/accept',headers=b).status_code==200
    assert c.get('/books?owner_id='+bid,headers=a).status_code==200
    t=c.post('/trades',headers=a,json={'wanted_book_id':y,'offered_book_id':x}).json()['trade_id']
    settings(c,b,private_library=True)
    assert c.get('/books?owner_id='+bid,headers=a).status_code==404
    assert c.get('/books/'+y+'/image',headers=a).status_code==404
    assert c.get('/books',headers=b).status_code==200
    assert c.post('/trades/'+t+'/accept',headers=b).status_code==409
    assert c.post('/friends/invites',headers=b).status_code==403
    assert c.post('/trades',headers=a,json={'wanted_book_id':y,'offered_book_id':x}).status_code==403


def test_mutual_friend_suggestions(client):
    c=client;aid,a=account(c,'alice');_,b=account(c,'bob');cid,ch=account(c,'carol')
    connect(c,a,b);connect(c,b,ch)
    settings(c,a,discoverable=True);settings(c,ch,discoverable=True)
    people=c.get('/people/suggestions',headers=a).json()
    assert people[0]['id']==cid and people[0]['mutual_friends']==1
    settings(c,ch,discoverable=False)
    assert c.get('/people/suggestions',headers=a).json()==[]


def test_secondary_preference_and_bulk_save(client):
    c=client;_,a=account(c,'alice');_,b=account(c,'bob')
    settings(c,a,secondary_review=False)
    r=c.post('/scans',headers=a,files={'front':('front.jpg',jpeg(),'image/jpeg')});assert r.status_code==202
    assert r.json()['enrichment_mode']=='off'
    process(c);bad=enqueue(c,a);process(c);pending=enqueue(c,a);foreign=enqueue(c,b)
    with main.db() as db:
        db.execute('UPDATE scans SET metadata=? WHERE id=?',(json.dumps({'title':None,'author':None}),bad['id']))
    assert c.post('/queue/accept-ready',headers=a,json={}).status_code==422
    r=c.post('/queue/accept-ready',headers=a,json={'acknowledge':True}).json()
    assert len(r['saved'])==1 and len(r['skipped'])==1
    assert c.get(pending['status_url'],headers=a).json()['status']=='queued'
    assert c.get(foreign['status_url'],headers=b).status_code==200
    assert c.post('/queue/accept-ready',headers=a,json={'acknowledge':True}).json()['saved']==[]
    assert c.get('/books',headers=a).json()[0]['available']==0


def test_reading_stats_and_trade_history(client):
    c=client;aid,a=account(c,'alice');_,b=account(c,'bob')
    x=add(c,a);duplicate=add(c,a);y=add(c,b)
    assert c.put('/reading/'+x,headers=b,json={'pages_read':10}).status_code==404
    assert c.put('/reading/'+x,headers=a,json={'pages_read':150,'review':'A good book','rating':4,'finished':True}).status_code==200
    stats=c.get('/me/stats',headers=a).json()
    assert stats['books']==2 and stats['unique_books']==1 and stats['reviews']==1 and stats['pages_read']==150
    connect(c,a,b);t=c.post('/trades',headers=a,json={'wanted_book_id':y,'offered_book_id':x}).json()['trade_id']
    c.post('/trades/'+t+'/accept',headers=b);c.post('/trades/'+t+'/confirm-handoff',headers=a);c.post('/trades/'+t+'/confirm-handoff',headers=b)
    stats=c.get('/me/stats',headers=a).json();assert stats['books_received']==stats['books_traded']==1
    assert c.put('/reading/'+x,headers=a,json={'pages_read':180,'review':'Still mine to review'}).status_code==200
    assert c.get('/me/stats',headers=b).json()['pages_read']==0
    assert c.get('/me/stats',headers=a).json()['pages_read']==180


def test_popular_excludes_private_and_duplicate_copies(client):
    c=client;_,a=account(c,'alice');_,b=account(c,'bob');_,ch=account(c,'carol')
    for h in (a,b,ch): add(c,h);settings(c,h,discoverable=True)
    add(c,a)
    assert c.get('/popular',headers=a).json()[0]['owners']==3
    settings(c,ch,private_library=True)
    assert c.get('/popular',headers=a).json()==[]


def test_admin_ban_remove_and_audit(client,monkeypatch):
    c=client;monkeypatch.setenv('BOOKBRIDGE_ADMINS','manager');mid,m=account(c,'manager');aid,a=account(c,'alice');_,b=account(c,'bob')
    x=add(c,a);y=add(c,b);connect(c,a,b)
    t=c.post('/trades',headers=a,json={'wanted_book_id':y,'offered_book_id':x}).json()['trade_id']
    assert c.get('/admin/stats',headers=a).status_code==403
    assert c.delete('/admin/books/'+x,headers=a).status_code==403
    assert c.delete('/admin/books/'+x,headers=m).status_code==204
    assert c.get('/books/'+x+'/image',headers=a).status_code==404
    assert c.get('/books',headers=a).json()==[]
    assert c.post('/trades/'+t+'/accept',headers=b).status_code==409
    assert c.patch('/admin/users/'+aid,headers=m,json={'banned':True}).status_code==200
    assert c.get('/me',headers=a).status_code==401
    assert c.post('/auth/login',json={'username':'alice','password':'my-testing-password'}).status_code==403
    assert c.patch('/admin/users/'+mid,headers=m,json={'banned':True}).status_code==409
    assert c.patch('/admin/users/'+aid,headers=m,json={'banned':False}).status_code==200
    assert c.post('/auth/login',json={'username':'alice','password':'my-testing-password'}).status_code==200
    assert len(c.get('/admin/events',headers=m).json()['actions'])==3


def test_bot_signals_and_limits(client):
    c=client
    assert c.post('/auth/register',json={'username':'robot','password':'12345678','website':'spam'}).status_code==422
    _,a=account(c,'alice')
    for i in range(20):
        assert c.post('/auth/login',json={'username':'alice','password':'wrongpass'}).status_code==401
    assert c.post('/auth/login',json={'username':'alice','password':'wrongpass'}).status_code==429
    with main.db() as db: assert db.execute('SELECT COUNT(*) FROM abuse_events').fetchone()[0]==2


def test_email_verification_and_opt_in_delivery(client,monkeypatch):
    c=client;_,a=account(c,'alice');bid,b=account(c,'bob')
    x=add(c,a);y=add(c,b);connect(c,a,b)
    monkeypatch.setenv('SMTP_HOST','mail.invalid');monkeypatch.setenv('SMTP_FROM','books@example.org')
    sent=[];monkeypatch.setattr(community,'deliver_email',lambda job:sent.append(job))
    settings(c,b,email='bob@example.org',email_notifications=True)
    c.post('/trades',headers=a,json={'wanted_book_id':y,'offered_book_id':x})
    with main.db() as db:assert db.execute('SELECT COUNT(*) FROM email_outbox').fetchone()[0]==0
    assert c.post('/me/email/send-code',headers=b).status_code==200
    community.send_next_email(main.db);assert sent[-1]['kind']=='verify'
    import re
    code=re.search(r'\b\d{6}\b',sent[-1]['body']).group()
    assert c.post('/me/email/verify',headers=b,json={'code':code}).status_code==200
    c.post('/trades',headers=a,json={'wanted_book_id':y,'offered_book_id':x})
    community.send_next_email(main.db);assert sent[-1]['kind']=='trade'
    settings(c,b,email='changed@example.org')
    assert not c.get('/me',headers=b).json()['email_verified']


def test_shared_library_permissions_queue_and_revocation(client,monkeypatch):
    c=client;monkeypatch.setenv('BOOKBRIDGE_ADMINS','manager');mid,m=account(c,'manager');aid,a=account(c,'alice');_,b=account(c,'bob')
    assert c.post('/libraries',headers=a,json={'name':'School'}).status_code==403
    lib=c.post('/libraries',headers=m,json={'name':'School'}).json()['id']
    assert c.post('/libraries/'+lib+'/members',headers=a,json={'username':'bob'}).status_code==404
    assert c.post('/libraries/'+lib+'/members',headers=m,json={'username':'alice'}).status_code==201
    assert c.get('/libraries',headers=a).json()[0]['name']=='School'
    r=c.post('/scans',headers=a,data={'library_id':lib},files={'front':('book.jpg',jpeg(),'image/jpeg')});assert r.status_code==202,r.text
    scan=r.json();process(c)
    assert c.get(scan['status_url'],headers=m).status_code==200
    assert c.get(scan['status_url'],headers=b).status_code==404
    assert c.get(scan['status_url']+'/images/0',headers=b).status_code==404
    assert c.post('/queue/accept-ready',headers=a,json={'acknowledge':True}).json()['saved']==[]
    saved=c.post('/libraries/'+lib+'/accept-ready',headers=m,json={'acknowledge':True}).json()['saved'];assert len(saved)==1
    book=saved[0]
    assert c.get('/books',headers=a).json()==[]
    assert c.get('/books?library_id='+lib,headers=a).json()[0]['id']==book
    assert c.get('/books?library_id='+lib,headers=b).status_code==404
    assert c.get('/books/'+book+'/image',headers=a).status_code==200
    assert c.delete('/libraries/'+lib+'/members/'+aid,headers=m).status_code==204
    assert c.get('/books/'+book+'/image',headers=a).status_code==404
    assert c.patch('/books/'+book,headers=a,json={'title':'x','author':'y'}).status_code==404
    assert c.post('/scans',headers=a,data={'library_id':lib},files={'front':('x.jpg',jpeg(),'image/jpeg')}).status_code==404
    assert c.delete('/libraries/'+lib+'/members/'+mid,headers=m).status_code==409
    assert c.get('/books?library_id='+lib,headers=m).json()[0]['id']==book


def test_shared_pending_queue_revocation(client,monkeypatch):
    c=client;monkeypatch.setenv('BOOKBRIDGE_ADMINS','manager');_,m=account(c,'manager');aid,a=account(c,'alice')
    lib=c.post('/libraries',headers=m,json={'name':'Community'}).json()['id']
    c.post('/libraries/'+lib+'/members',headers=m,json={'username':'alice'})
    scan=c.post('/scans',headers=a,data={'library_id':lib},files={'front':('x.jpg',jpeg(),'image/jpeg')}).json()
    c.delete('/libraries/'+lib+'/members/'+aid,headers=m)
    assert c.get('/scans',headers=a).json()==[]
    assert c.get(scan['status_url'],headers=a).status_code==404
    assert c.delete(scan['status_url'],headers=a).status_code==404
    process(c)
    assert c.post(scan['status_url']+'/save',headers=a,json={'title':'x','author':'y'}).status_code==404
    assert c.get(scan['status_url'],headers=m).json()['status']=='ready'


def test_idempotent_community_migration_preserves_data(client):
    c=client;aid,a=account(c,'alice');book=add(c,a)
    settings(c,a,display_name='Alice Example',secondary_review=False)
    community.initialize(main.db);community.initialize(main.db)
    assert c.get('/me',headers=a).json()['display_name']=='Alice Example'
    assert c.get('/books',headers=a).json()[0]['id']==book
