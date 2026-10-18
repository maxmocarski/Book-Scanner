import asyncio
import json
import threading
from io import BytesIO
from PIL import Image
from test_backend import client,account,jpeg,enqueue,process
from api import main
from api.schema import initialize
from core.scanning import Scanner,Metadata
from core.batch import ShelfPhoto,Spine


def response(count=3):
    return ShelfPhoto(books=[Spine(metadata=Metadata(title='Book '+str(i+1),author='Author'),left=i/count,right=(i+1)/count,unclear=(i==1)) for i in range(count)])


def shelf(c,h,count=3,library='',name='A'):
    return c.post('/scans',headers=h,data={'scan_mode':'shelf','book_count':count,'shelf':name,'library_id':library,'enrichment':'off'},files={'front':('shelf.jpg',jpeg(),'image/jpeg')})


def test_shelf_expands_atomically_left_to_right_and_preserves_sequence(client,monkeypatch):
    c=client;_,a=account(c,'alice')
    async def generate(self,*args,**kwargs):
        result=response();result.books.reverse();return result
    monkeypatch.setattr(Scanner,'generate',generate)
    first=c.post('/scans',headers=a,data={'shelf':'A'},files={'front':('x.jpg',jpeg(),'image/jpeg')}).json()
    parent=shelf(c,a).json()
    last=c.post('/scans',headers=a,data={'shelf':'A'},files={'front':('x.jpg',jpeg(),'image/jpeg')}).json()
    assert first['shelf_position']==1 and parent['shelf_position']==2 and last['shelf_position']==5
    process(c);process(c)
    result=c.get(parent['status_url'],headers=a).json()
    assert result['status']=='expanded' and len(result['child_scan_ids'])==3
    assert parent['id'] not in [r['id'] for r in c.get('/scans',headers=a).json()]
    children=[c.get('/scans/'+identifier,headers=a).json() for identifier in result['child_scan_ids']]
    assert [r['original_metadata']['title'] for r in children]==['Book 1','Book 2','Book 3']
    assert [r['shelf_position'] for r in children]==[2,3,4]
    assert all(r['batch_id']==parent['id'] for r in children)
    assert c.post(parent['status_url']+'/save',headers=a,json={'title':'x','author':'y'}).status_code==409
    while process(c):pass
    assert 'unclear' in ' '.join(c.get(children[1]['status_url'],headers=a).json()['warnings'])
    # Save in reverse order: shelf numbers stay physical-order, added order tracks saving.
    ids=[]
    for child in reversed(children):
        data=c.get(child['status_url'],headers=a).json()
        ids.append(c.post(child['status_url']+'/save',headers=a,json=data['metadata']).json()['book_id'])
    books={b['id']:b for b in c.get('/books',headers=a).json()}
    assert [books[i]['title'] for i in sorted(ids,key=lambda i:books[i]['added_order'])]==['Book 3','Book 2','Book 1']
    assert [books[i]['shelf_position'] for i in ids]==[4,3,2]
    initialize(main.db)
    assert c.get(parent['status_url'],headers=a).json()['child_scan_ids']==result['child_scan_ids']
    assert len(c.get('/books',headers=a).json())==3


def test_batch_limits_mismatch_retry_and_no_false_bulk_save(client,monkeypatch):
    c=client;_,a=account(c,'alice');scanner=c.app.state.scanner
    assert shelf(c,a,count=6).status_code==422
    assert c.post('/scans',headers=a,data={'scan_mode':'shelf'},files=[('front',('a.jpg',jpeg(),'image/jpeg')),('back',('b.jpg',jpeg(),'image/jpeg'))]).status_code==422
    scanner.settings.max_user_pending=3
    parent=shelf(c,a).json()
    assert c.post('/scans',headers=a,files={'front':('x.jpg',jpeg(),'image/jpeg')}).status_code==429
    async def mismatch(self,*args,**kwargs):return response(2)
    monkeypatch.setattr(Scanner,'generate',mismatch)
    process(c)
    failed=c.get(parent['status_url'],headers=a).json();assert failed['status']=='failed' and 'found 2' in failed['error']
    assert len(c.get('/scans',headers=a).json())==1
    async def correct(self,*args,**kwargs):return response(3)
    monkeypatch.setattr(Scanner,'generate',correct)
    assert c.post(parent['status_url']+'/retry',headers=a).status_code==202
    process(c)
    result=c.get(parent['status_url'],headers=a).json();assert len(result['child_scan_ids'])==3
    while process(c):pass
    saved=c.post('/queue/accept-ready',headers=a,json={'acknowledge':True}).json()
    assert len(saved['saved'])==3 and saved['skipped']==[]
    assert c.get('/scans',headers=a).json()==[]


def test_bad_spine_boundaries_fail_without_partial_children(client,monkeypatch):
    c=client;_,a=account(c,'alice')
    async def overlap(self,*args,**kwargs):
        return ShelfPhoto(books=[Spine(metadata=Metadata(),left=0,right=.8),Spine(metadata=Metadata(),left=.4,right=1)])
    monkeypatch.setattr(Scanner,'generate',overlap)
    parent=shelf(c,a,2).json();process(c)
    assert c.get(parent['status_url'],headers=a).json()['status']=='failed'
    assert len(c.get('/scans',headers=a).json())==1
    async def too_many(self,*args,**kwargs):return ShelfPhoto(too_many=True)
    monkeypatch.setattr(Scanner,'generate',too_many)
    c.post(parent['status_url']+'/retry',headers=a);process(c)
    assert 'no more than 5' in c.get(parent['status_url'],headers=a).json()['error']


def test_shared_batch_deleted_during_detection_stays_deleted(client,monkeypatch):
    c=client;monkeypatch.setenv('BOOKBRIDGE_ADMINS','manager');_,a=account(c,'manager')
    lib=c.post('/libraries',headers=a,json={'name':'School'}).json()['id']
    started=threading.Event();release=threading.Event()
    async def wait(self,*args,**kwargs):
        started.set();await asyncio.to_thread(release.wait,5);return response()
    monkeypatch.setattr(Scanner,'generate',wait)
    shelf(c,a,library=lib)
    worker=threading.Thread(target=process,args=(c,));worker.start();assert started.wait(3)
    assert c.request('DELETE','/admin/libraries/'+lib,headers=a,json={'confirm_name':'School'}).status_code==204
    release.set();worker.join(5);assert not worker.is_alive()
    with main.db() as db:assert db.execute('SELECT COUNT(*) FROM scans').fetchone()[0]==0


def test_five_spines_without_shelf_keep_unclear_book_for_manual_review(client,monkeypatch):
    c=client;_,a=account(c,'alice')
    async def five(self,*args,**kwargs):
        result=response(5);result.books[1].metadata=Metadata();result.books[1].unclear=True;return result
    monkeypatch.setattr(Scanner,'generate',five)
    parent=shelf(c,a,count=5,name='').json();process(c)
    child_ids=c.get(parent['status_url'],headers=a).json()['child_scan_ids']
    assert len(child_ids)==5
    while process(c):pass
    drafts=c.get('/scans',headers=a).json()
    assert len(drafts)==5 and all(r['shelf_position'] is None for r in drafts)
    unclear=c.get('/scans/'+child_ids[1],headers=a).json()
    assert unclear['metadata']['title'] is None and unclear['metadata']['author'] is None
    result=c.post('/queue/accept-ready',headers=a,json={'acknowledge':True}).json()
    assert len(result['saved'])==4 and len(result['skipped'])==1
    assert c.post(unclear['status_url']+'/save',headers=a,json={'title':'Manually checked book','author':'Checked author'}).status_code==201
    books=c.get('/books',headers=a).json()
    assert len(books)==5 and max(books,key=lambda b:b['added_order'])['title']=='Manually checked book'
