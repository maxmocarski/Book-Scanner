from test_backend import client, account, jpeg, process
from api import main
from api.schema import initialize


def test_optional_shelf_survives_scan_review_and_edit(client):
    c=client;_,a=account(c,'alice')
    result=c.post('/scans',headers=a,data={'shelf':'  Office — shelf 2  '},files={'front':('cover.jpg',jpeg(),'image/jpeg')})
    assert result.status_code==202,result.text
    scan=result.json();assert scan['shelf']=='Office — shelf 2'
    process(c)
    ready=c.get(scan['status_url'],headers=a).json()
    assert ready['shelf']=='Office — shelf 2'
    saved=c.post(scan['status_url']+'/save',headers=a,json=ready['metadata'])
    assert saved.status_code==201,saved.text
    book=c.get('/books',headers=a).json()[0]
    assert book['shelf']=='Office — shelf 2'
    body={k:book[k] for k in ('title','author','isbn')}
    # Older clients that omit shelf preserve it; empty text explicitly clears it.
    assert c.patch('/books/'+book['id'],headers=a,json=body).json()['shelf']==book['shelf']
    assert c.patch('/books/'+book['id'],headers=a,json={**body,'shelf':' Bedroom '}).json()['shelf']=='Bedroom'
    assert c.patch('/books/'+book['id'],headers=a,json={**body,'shelf':''}).json()['shelf']==''
    initialize(main.db)
    assert c.get('/books',headers=a).json()[0]['shelf']==''
    assert c.post('/scans',headers=a,data={'shelf':'x'*101},files={'front':('cover.jpg',jpeg(),'image/jpeg')}).status_code==422
    assert c.patch('/books/'+book['id'],headers=a,json={**body,'shelf':'x'*101}).status_code==422


def test_bulk_keeps_each_shelf_in_personal_and_shared_libraries(client,monkeypatch):
    c=client;monkeypatch.setenv('BOOKBRIDGE_ADMINS','manager');_,a=account(c,'manager')
    lib=c.post('/libraries',headers=a,json={'name':'Town library'}).json()['id']
    for library_id,path in [('', '/queue/accept-ready'),(lib,'/libraries/'+lib+'/accept-ready')]:
        for shelf in ['A1','B2','']:
            r=c.post('/scans',headers=a,data={'shelf':shelf,'library_id':library_id},files={'front':('cover.jpg',jpeg(),'image/jpeg')})
            assert r.status_code==202,r.text
            process(c)
        result=c.post(path,headers=a,json={'acknowledge':True}).json()
        assert len(result['saved'])==3 and not result['skipped']
        books=c.get('/books',headers=a,params={'library_id':library_id} if library_id else {}).json()
        assert sorted(b['shelf'] for b in books)==['','A1','B2']
        assert len({b['edition_key'] for b in books})==1


def test_shelf_numbers_follow_scan_order_and_survive_bulk(client,monkeypatch):
    c=client;monkeypatch.setenv('BOOKBRIDGE_ADMINS','manager');_,a=account(c,'manager');_,b=account(c,'reader')
    lib=c.post('/libraries',headers=a,json={'name':'Shared'}).json()['id']
    c.post('/libraries/'+lib+'/members',headers=a,json={'username':'reader'})
    def scan(headers,shelf,library=''):
        r=c.post('/scans',headers=headers,data={'shelf':shelf,'library_id':library},files={'front':('cover.jpg',jpeg(),'image/jpeg')})
        assert r.status_code==202,r.text
        return r.json()
    first=scan(a,'Shelf A');second=scan(a,'shelf a');other=scan(a,'Shelf B')
    assert [s['shelf_position'] for s in [first,second,other]]==[1,2,1]
    assert first['shelf_label']=='Shelf A (1)'
    assert scan(b,'Shelf A')['shelf_position']==1
    assert scan(a,'Shelf A',lib)['shelf_position']==1
    assert scan(b,'Shelf A',lib)['shelf_position']==2
    assert scan(a,'')['shelf_position'] is None
    while process(c):pass
    assert len(c.post('/queue/accept-ready',headers=a,json={'acknowledge':True}).json()['saved'])==4
    books=c.get('/books',headers=a).json()
    original=next(book for book in books if book['shelf_label']=='Shelf A (1)')
    fields={k:original[k] for k in ('title','author','isbn')}
    assert c.patch('/books/'+original['id'],headers=a,json={**fields,'shelf':'Shelf A'}).json()['shelf_position']==1
    moved=c.patch('/books/'+original['id'],headers=a,json={**fields,'shelf':'Shelf B'}).json()
    assert moved['shelf_label']=='Shelf B (2)'
    assert c.patch('/books/'+original['id'],headers=a,json={**fields,'shelf':''}).json()['shelf_position'] is None
    third=scan(a,'Shelf A');assert third['shelf_position']==3
    c.delete(third['status_url'],headers=a)
    assert scan(a,'Shelf A')['shelf_position']==4
    from core import shelves
    with main.db() as db:shelves.initialize(db)
    assert scan(a,'Shelf A')['shelf_position']==5


def test_older_shelves_get_stable_numbers_on_upgrade(client):
    c=client;_,a=account(c,'alice')
    for shelf in ['A','A','B']:
        c.post('/scans',headers=a,data={'shelf':shelf},files={'front':('cover.jpg',jpeg(),'image/jpeg')});process(c)
    c.post('/queue/accept-ready',headers=a,json={'acknowledge':True})
    # Simulate a pre-numbering database containing books with shelf names.
    with main.db() as db:
        db.execute('UPDATE books SET shelf_position=NULL')
        db.execute('DROP TABLE shelf_counters')
        db.execute('ALTER TABLE scans DROP COLUMN shelf_position')
        db.execute('ALTER TABLE books DROP COLUMN shelf_position')
    initialize(main.db)
    books=c.get('/books',headers=a).json()
    assert sorted(b['shelf_position'] for b in books if b['shelf']=='A')==[1,2]
    assert next(b for b in books if b['shelf']=='B')['shelf_position']==1
    before={b['id']:b['shelf_position'] for b in books}
    initialize(main.db)
    assert {b['id']:b['shelf_position'] for b in c.get('/books',headers=a).json()}==before
