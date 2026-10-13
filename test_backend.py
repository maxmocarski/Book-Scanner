from io import BytesIO
import sqlite3
import httpx
from fastapi.testclient import TestClient
from PIL import Image
import pytest
import main

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'DATA', tmp_path)
    async def identify(images):
        assert len(images) in (1,2)
        return main.Metadata(title='The Great Gatsby', author='F. Scott Fitzgerald', isbn='9780743273565')
    monkeypatch.setattr(main, 'identify', identify)
    with TestClient(main.app) as c:
        yield c

def account(c, username):
    r = c.post('/auth/register', json={'username':username, 'password':'my-testing-password'})
    assert r.status_code == 201
    j = r.json()
    return j['user_id'], {'Authorization':'Bearer '+j['access_token']}

def add(c, headers):
    out = BytesIO()
    Image.new('RGB',(100,150),'blue').save(out,format='JPEG')
    r = c.post('/scans',headers=headers,files={'cover':('book.jpg',out.getvalue(),'image/jpeg')})
    assert r.status_code==201, r.text
    scan = r.json()
    r = c.post('/scans/'+scan['scan_id']+'/save', headers=headers,json={'title':scan['title'],'author':scan['author'],'isbn':scan['isbn'],'available':True})
    assert r.status_code==201, r.text
    assert c.post('/scans/'+scan['scan_id']+'/save',headers=headers,json={'title':'x','author':'y'}).status_code==404
    return r.json()['book_id']

def connect(c, a, b):
    code=c.post('/friends/invites',headers=a).json()['code']
    assert c.post('/friends/accept',headers=b,json={'code':code}).status_code==200
    assert c.post('/friends/accept',headers=b,json={'code':code}).status_code==404

def test_privacy_and_scan_save(client):
    c=client
    aid,a=account(c,'alice'); _,b=account(c,'bob')
    book=add(c,a)
    assert c.get('/books').status_code in (401,403)
    assert c.get('/books',headers=b,params={'owner_id':aid}).status_code==404
    assert c.get(f'/books/{book}/image',headers=b).status_code==404
    assert c.patch('/books/'+book,headers=b,json={'title':'x','author':'y'}).status_code==404
    connect(c,a,b)
    assert len(c.get('/books',headers=b,params={'owner_id':aid}).json())==1
    assert c.get(f'/books/{book}/image',headers=b).headers['content-type']=='image/jpeg'
    with main.db() as db:
        assert db.execute('SELECT COUNT(*) FROM drafts').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM books').fetchone()[0]==1
    assert c.post('/auth/logout',headers=a).status_code==204
    assert c.get('/books',headers=a).status_code==401

def test_swap_requires_both_and_reserves(client):
    c=client
    aid,a=account(c,'alice'); bid,b=account(c,'bob'); _,other=account(c,'outsider')
    x=add(c,a); y=add(c,b); z=add(c,a)
    assert c.post('/trades',headers=a,json={'wanted_book_id':y,'offered_book_id':x}).status_code==403
    connect(c,a,b)
    t=c.post('/trades',headers=a,json={'wanted_book_id':y,'offered_book_id':x}).json()['trade_id']
    competing=c.post('/trades',headers=a,json={'wanted_book_id':y,'offered_book_id':z}).json()['trade_id']
    assert c.post(f'/trades/{t}/accept',headers=a).status_code==403
    assert c.post(f'/trades/{t}/accept',headers=other).status_code==404
    assert c.post(f'/trades/{t}/accept',headers=b).status_code==200
    assert c.post(f'/trades/{competing}/accept',headers=b).status_code==409
    assert c.patch('/books/'+x,headers=a,json={'title':'changed','author':'someone'}).status_code==409
    assert c.post(f'/trades/{t}/confirm-handoff',headers=a).json()['status']=='accepted'
    assert x in [r['id'] for r in c.get('/books',headers=a).json()]
    assert c.post(f'/trades/{t}/confirm-handoff',headers=b).json()['status']=='completed'
    assert y in [r['id'] for r in c.get('/books',headers=a).json()]
    assert x in [r['id'] for r in c.get('/books',headers=b).json()]
    assert c.post(f'/trades/{t}/confirm-handoff',headers=b).status_code==409

def test_validation_and_auth(client):
    c=client
    _,a=account(c,'alice')
    assert c.post('/auth/register',json={'username':'ALICE','password':'my-testing-password'}).status_code==409
    assert c.post('/auth/login',json={'username':'alice','password':'wrong-password'}).status_code==401
    assert c.post('/auth/login',json={'username':'ALICE','password':'my-testing-password'}).status_code==200
    assert c.post('/scans',headers=a,files={'cover':('x.jpg',b'not an image','image/jpeg')}).status_code==415
    assert main.valid_isbn('978-0-7432-7356-5')=='9780743273565'
    assert main.valid_isbn('0-306-40615-2')=='0306406152'
    with pytest.raises(ValueError):main.valid_isbn('9780743273566')
    with pytest.raises(ValueError):main.valid_isbn('1234567890128')

def test_remove_friend_cancels_trade(client):
    c=client
    _,a=account(c,'alice'); bid,b=account(c,'bob')
    x=add(c,a);y=add(c,b);connect(c,a,b)
    t=c.post('/trades',headers=a,json={'wanted_book_id':y,'offered_book_id':x}).json()['trade_id']
    c.post(f'/trades/{t}/accept',headers=b)
    assert c.delete('/friends/'+bid,headers=a).status_code==204
    assert c.post(f'/trades/{t}/confirm-handoff',headers=b).status_code==409
    assert c.get(f'/books/{x}/image',headers=b).status_code==404
    assert c.patch('/books/'+x,headers=a,json={'title':'x','author':'y','available':True}).status_code==200

def test_model_payload_and_invalid_isbn(client, monkeypatch):
    async def fake_post(self,url,json):
        assert url.endswith('/api/generate')
        assert json['model']=='gemma3:12b'
        assert len(json['images'])==2
        assert json['format']['type']=='object'
        return httpx.Response(200,json={'response':'{"title":"Book","author":"Author","isbn":"9780743273566"}'},request=httpx.Request('POST',url))
    # Restore real identify after the fixture's replacement.
    import importlib.util
    spec=importlib.util.spec_from_file_location('original',main.__file__)
    original=importlib.util.module_from_spec(spec);spec.loader.exec_module(original)
    monkeypatch.setattr(main,'identify',original.identify)
    monkeypatch.setattr(httpx.AsyncClient,'post',fake_post)
    _,a=account(client,'alice')
    out=BytesIO();Image.new('RGB',(100,100)).save(out,format='PNG')
    image=out.getvalue()
    r=client.post('/scans',headers=a,files={'cover':('cover.png',image,'image/png'),'details':('back.png',image,'image/png')})
    assert r.status_code==201,r.text
    assert r.json()['isbn'] is None
    assert any('failed validation' in w for w in r.json()['warnings'])

def test_draft_owner_and_expiry(client):
    c=client
    _,a=account(c,'alice');_,b=account(c,'bob')
    out=BytesIO();Image.new('RGB',(100,100)).save(out,format='JPEG')
    scan=c.post('/scans',headers=a,files={'cover':('x.jpg',out.getvalue(),'image/jpeg')}).json()['scan_id']
    body={'title':'x','author':'y','isbn':None}
    assert c.post('/scans/'+scan+'/save',headers=b,json=body).status_code==404
    assert c.post('/scans/'+scan+'/save',headers=a,json={**body,'isbn':'9780743273566'}).status_code==422
    with main.db() as db:
        db.execute('UPDATE drafts SET expires=0 WHERE id=?',(scan,))
    assert c.post('/scans/'+scan+'/save',headers=a,json=body).status_code==404
    main.cleanup_expired()
    with main.db() as db:
        assert db.execute('SELECT COUNT(*) FROM drafts').fetchone()[0]==0

def test_model_errors(client, monkeypatch):
    import importlib.util
    spec=importlib.util.spec_from_file_location('original_errors',main.__file__)
    original=importlib.util.module_from_spec(spec);spec.loader.exec_module(original)
    monkeypatch.setattr(main,'identify',original.identify)
    async def broken(self,url,json):
        return httpx.Response(200,json={'response':'not json'},request=httpx.Request('POST',url))
    monkeypatch.setattr(httpx.AsyncClient,'post',broken)
    _,a=account(client,'alice')
    out=BytesIO();Image.new('RGB',(100,100)).save(out,format='PNG')
    assert client.post('/scans',headers=a,files={'cover':('x.png',out.getvalue(),'image/png')}).status_code==502
    with main.db() as db:
        assert db.execute('SELECT COUNT(*) FROM drafts').fetchone()[0]==0
