import asyncio
from io import BytesIO
import threading
from fastapi.testclient import TestClient
from PIL import Image
import pytest
import api.main as main
from core.scanning import Metadata, Scanner, ScanError, baseline
from api.schema import initialize
@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main,'DATA',tmp_path)
    monkeypatch.setattr(main.app.state,'worker_enabled',False,raising=False)
    async def identify(self,images):
        assert 1<=len(images)<=3
        return Metadata(title='The Great Gatsby',author='F. Scott Fitzgerald',isbn='9780743273565')
    async def enrich(self,raw,mode):
        m,n,c=baseline(raw)
        return m,n,c,[],None
    monkeypatch.setattr(Scanner,'identify',identify)
    monkeypatch.setattr(Scanner,'enrich',enrich)
    with TestClient(main.app) as c:yield c
def account(c,name):
    r=c.post('/auth/register',json={'username':name,'password':'my-testing-password'})
    assert r.status_code==201,r.text
    j=r.json();return j['user_id'],{'Authorization':'Bearer '+j['access_token']}
def jpeg():
    out=BytesIO();Image.new('RGB',(100,150),'blue').save(out,format='JPEG');return out.getvalue()
def enqueue(c,h,views=('front',),mode='cleanup'):
    r=c.post('/scans',headers=h,data={'enrichment':mode},files=[(v,(v+'.jpg',jpeg(),'image/jpeg')) for v in views])
    assert r.status_code==202,r.text
    return r.json()
def process(c):return c.portal.call(main.app.state.scanner.process_next)
def add(c,h,views=('front',)):
    s=enqueue(c,h,views);assert s['status']=='queued';assert process(c)
    r=c.get(s['status_url'],headers=h).json();assert r['status']=='ready',r
    body={**r['metadata'],'available':True}
    saved=c.post(s['status_url']+'/save',headers=h,json=body);assert saved.status_code==201,saved.text
    assert c.post(s['status_url']+'/save',headers=h,json=body).status_code==404
    return saved.json()['book_id']
def connect(c,a,b):
    code=c.post('/friends/invites',headers=a).json()['code']
    assert c.post('/friends/accept',headers=b,json={'code':code}).status_code==200
    assert c.post('/friends/accept',headers=b,json={'code':code}).status_code==404
def test_privacy_three_images_and_scan_save(client):
    c=client;aid,a=account(c,'alice');_,b=account(c,'bob')
    book=add(c,a,('front','spine','back'))
    assert c.get('/books').status_code in (401,403)
    assert c.get('/books',headers=b,params={'owner_id':aid}).status_code==404
    for i in range(3):assert c.get(f'/books/{book}/images/{i}',headers=b).status_code==404
    assert c.patch('/books/'+book,headers=b,json={'title':'x','author':'y'}).status_code==404
    connect(c,a,b)
    rows=c.get('/books',headers=b,params={'owner_id':aid}).json()
    assert [x['view'] for x in rows[0]['images']]==['front','spine','back']
    for i in range(3):assert c.get(f'/books/{book}/images/{i}',headers=b).headers['content-type']=='image/jpeg'
    assert c.get(f'/books/{book}/image',headers=b).content==c.get(f'/books/{book}/images/0',headers=b).content
    with main.db() as db:
        assert db.execute('SELECT COUNT(*) FROM scans').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM scan_images').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM book_images').fetchone()[0]==3
    assert c.post('/auth/logout',headers=a).status_code==204
    assert c.get('/books',headers=a).status_code==401
def test_swap_requires_both_and_reserves(client):
    c=client;aid,a=account(c,'alice');bid,b=account(c,'bob');_,other=account(c,'outsider')
    x=add(c,a,('front','spine','back'));y=add(c,b);z=add(c,a)
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
    moved=next(r for r in c.get('/books',headers=b).json() if r['id']==x);assert len(moved['images'])==3
    assert c.post(f'/trades/{t}/confirm-handoff',headers=b).status_code==409
def test_validation_and_auth(client):
    c=client;_,a=account(c,'alice')
    assert c.post('/auth/register',json={'username':'ALICE','password':'my-testing-password'}).status_code==409
    assert c.post('/auth/login',json={'username':'alice','password':'wrong-password'}).status_code==401
    assert c.post('/auth/login',json={'username':'ALICE','password':'my-testing-password'}).status_code==200
    assert c.post('/scans',headers=a,files={'front':('x.jpg',b'not an image','image/jpeg')}).status_code==415
    assert main.valid_isbn('978-0-7432-7356-5')=='9780743273565'
    assert main.valid_isbn('0-306-40615-2')=='0306406152'
    with pytest.raises(ValueError):main.valid_isbn('9780743273566')
    with pytest.raises(ValueError):main.valid_isbn('1234567890128')
    for count in (2,4):assert c.post('/scans',headers=a,files=[('front',('x.jpg',jpeg(),'image/jpeg'))]*count).status_code==422
    assert c.post('/scans',headers=a,files={'spine':('x.jpg',jpeg(),'image/jpeg')}).status_code==422
    assert c.post('/scans',headers=a,data={'enrichment':'invalid'},files={'front':('x.jpg',jpeg(),'image/jpeg')}).status_code==422
    assert len(enqueue(c,a,('cover','details'))['images'])==2
def test_remove_friend_cancels_trade(client):
    c=client;_,a=account(c,'alice');bid,b=account(c,'bob')
    x=add(c,a);y=add(c,b);connect(c,a,b)
    t=c.post('/trades',headers=a,json={'wanted_book_id':y,'offered_book_id':x}).json()['trade_id'];c.post(f'/trades/{t}/accept',headers=b)
    assert c.delete('/friends/'+bid,headers=a).status_code==204
    assert c.post(f'/trades/{t}/confirm-handoff',headers=b).status_code==409
    assert c.get(f'/books/{x}/image',headers=b).status_code==404
    assert c.patch('/books/'+x,headers=a,json={'title':'x','author':'y','available':True}).status_code==200
def test_owner_expiry_and_pending_save(client):
    c=client;_,a=account(c,'alice');_,b=account(c,'bob')
    s=enqueue(c,a,('front','back'));path=s['status_url'];body={'title':'x','author':'y','isbn':None}
    assert c.get(path,headers=b).status_code==404
    assert c.get(path+'/images/0',headers=b).status_code==404
    assert c.post(path+'/save',headers=b,json=body).status_code==404
    assert c.delete(path,headers=b).status_code==404
    assert c.post(path+'/save',headers=a,json=body).status_code==409
    process(c)
    assert c.post(path+'/save',headers=a,json={**body,'isbn':'9780743273566'}).status_code==422
    with main.db() as db:db.execute('UPDATE scans SET expires=0 WHERE id=?',(s['scan_id'],))
    assert c.get(path,headers=a).status_code==404
    main.cleanup_expired()
    with main.db() as db:
        assert db.execute('SELECT COUNT(*) FROM scans').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM scan_images').fetchone()[0]==0
def test_fifo_and_queue_limits(client):
    c=client;_,a=account(c,'alice');main.app.state.scanner.settings.max_user_pending=2
    one=enqueue(c,a);two=enqueue(c,a,('front','back'))
    assert one['queue_position']==1 and two['queue_position']==2
    assert c.post('/scans',headers=a,files={'front':('x.jpg',jpeg(),'image/jpeg')}).status_code==429
    assert process(c)
    assert c.get(one['status_url'],headers=a).json()['status']=='ready'
    assert c.get(two['status_url'],headers=a).json()['queue_position']==1
    assert process(c);assert c.get(two['status_url'],headers=a).json()['status']=='ready'
    assert not process(c)
def test_cancel_in_flight_and_failure_retry(client,monkeypatch):
    c=client;_,a=account(c,'alice');first=enqueue(c,a);second=enqueue(c,a)
    started=threading.Event();gate=asyncio.Event()
    async def blocked(self,images):
        started.set();await gate.wait();return Metadata(title='Book',author='Author')
    monkeypatch.setattr(Scanner,'identify',blocked)
    future=c.portal.start_task_soon(main.app.state.scanner.process_next)
    assert started.wait(timeout=3)
    assert c.get(first['status_url'],headers=a).json()['status']=='identifying'
    third=enqueue(c,a,('front','spine','back'));assert third['status']=='queued'
    assert c.delete(first['status_url'],headers=a).status_code==204
    c.portal.call(gate.set);assert future.result(timeout=3)
    assert c.get(first['status_url'],headers=a).status_code==404
    async def broken(self,images):raise ScanError('Model timed out. You can retry this scan.')
    monkeypatch.setattr(Scanner,'identify',broken);assert process(c)
    assert c.get(second['status_url'],headers=a).json()['status']=='failed'
    retried=c.post(second['status_url']+'/retry',headers=a);assert retried.status_code==202
    assert retried.json()['queue_position']==2
    assert c.post(second['status_url']+'/retry',headers=a).status_code==409
    assert c.delete(third['status_url'],headers=a).status_code==204
    monkeypatch.setattr(Scanner,'identify',blocked);process(c)
    assert c.get(second['status_url'],headers=a).json()['status']=='ready'
def test_restart_recovery(client):
    c=client;_,a=account(c,'alice');one=enqueue(c,a,('front','spine','back'));two=enqueue(c,a)
    with main.db() as db:db.execute("UPDATE scans SET status='enriching' WHERE id=?",(one['scan_id'],))
    initialize(main.db)
    assert c.get(one['status_url'],headers=a).json()['status']=='queued'
    assert len(c.get(one['status_url'],headers=a).json()['images'])==3
    assert process(c);assert c.get(one['status_url'],headers=a).json()['status']=='ready'
    assert c.get(two['status_url'],headers=a).json()['status']=='queued'
def test_delete_cascades_images(client):
    c=client;_,a=account(c,'alice');book=add(c,a,('front','spine','back'))
    assert c.delete('/books/'+book,headers=a).status_code==204
    with main.db() as db:assert db.execute('SELECT COUNT(*) FROM book_images').fetchone()[0]==0
def test_frontend_and_private_trade_labels(client):
    response=client.get('/')
    assert response.status_code==200
    assert '<title>BookBridge' in response.text
    assert '/static/app.js' in response.text
    for path in ('/static/app.js','/static/app.css','/static/icon.svg'):
        assert client.get(path).status_code==200
    _,a=account(client,'reader');_,b=account(client,'friend')
    x=add(client,a);y=add(client,b);connect(client,a,b)
    client.post('/trades',headers=a,json={'wanted_book_id':y,'offered_book_id':x})
    rows=client.get('/trades',headers=a).json()
    assert rows[0]['sender_username']=='reader'
    assert rows[0]['recipient_username']=='friend'
    assert rows[0]['wanted_title']=='The Great Gatsby'
