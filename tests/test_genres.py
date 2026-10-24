import asyncio
from test_backend import client, account, add
from api import main
from api.schema import initialize
from core import genres
from core.scanning import Scanner, ScanError


def run(c):
    return asyncio.run(genres.process_next(main.app.state.scanner))


def test_check_persists_and_retries_without_duplicate_jobs(client,monkeypatch):
    c=client;_,a=account(c,'alice');book=add(c,a)
    async def generate(self,model,prompt,schema,images=None):
        assert model==self.settings.text_model and images is None
        assert schema is genres.Classification
        return genres.Classification(genre='Fiction')
    monkeypatch.setattr(Scanner,'generate',generate)
    assert c.post('/genre-checks',headers=a).json()=={'queued':1}
    assert c.post('/genre-checks',headers=a).json()=={'queued':0}
    assert run(c)
    assert c.get('/books',headers=a).json()[0]['genre']=='Fiction'
    assert c.get('/genre-checks',headers=a).json()['counts']['done']==1
    assert c.post('/genre-checks',headers=a).json()=={'queued':0}
    initialize(main.db)
    assert c.get('/books',headers=a).json()[0]['genre']=='Fiction'
    # An older client editing without genre preserves the label.
    result=c.patch('/books/'+book,headers=a,json={'title':'Book','author':'Author'})
    assert result.json()['genre']=='Fiction'
    assert c.patch('/books/'+book,headers=a,json={'title':'Book','author':'Author','genre':'made up'}).status_code==422
    assert c.patch('/books/'+book,headers=a,json={'title':'Book','author':'Author','genre':''}).status_code==200
    async def fail(*args,**kwargs):raise ScanError('offline')
    monkeypatch.setattr(Scanner,'generate',fail)
    assert c.post('/genre-checks',headers=a).json()['queued']==1
    assert run(c)
    assert c.get('/genre-checks',headers=a).json()['counts']['failed']==1
    monkeypatch.setattr(Scanner,'generate',generate)
    assert c.post('/genre-checks',headers=a).json()['queued']==1
    assert run(c)
    assert c.get('/books',headers=a).json()[0]['genre']=='Fiction'


def test_genre_access_and_scope(client,monkeypatch):
    c=client;aid,a=account(c,'alice');_,b=account(c,'bob');add(c,a)
    assert c.post('/genre-checks').status_code in (401,403)
    assert c.post('/genre-checks',headers=b).json()=={'queued':0}
    assert c.get('/genre-checks',headers=b).json()['missing']==0
    monkeypatch.setenv('BOOKBRIDGE_ADMINS','alice')
    lib=c.post('/libraries',headers=a,json={'name':'Shared'}).json()['id']
    assert c.post('/genre-checks',headers=b,params={'library_id':lib}).status_code==404
    # Queueing a shared-library job requires management, even for members.
    with main.db() as db:
        bid=db.execute("SELECT id FROM users WHERE username='bob'").fetchone()['id']
        db.execute('INSERT INTO library_members(library_id,user_id) VALUES(?,?)',(lib,bid))
    assert c.get('/genre-checks',headers=b,params={'library_id':lib}).json()['can_check'] is False
    assert c.post('/genre-checks',headers=b,params={'library_id':lib}).status_code in (403,404)


def test_manual_edit_during_inference_wins(client,monkeypatch):
    c=client;_,a=account(c,'alice');book=add(c,a)
    c.post('/genre-checks',headers=a)
    async def generate(*args,**kwargs):
        response=c.patch('/books/'+book,headers=a,json={'title':'Edited','author':'Author','genre':'History'})
        assert response.status_code==200
        return genres.Classification(genre='Fiction')
    monkeypatch.setattr(Scanner,'generate',generate)
    run(c)
    result=c.get('/books',headers=a).json()[0]
    assert result['genre']=='History' and result['title']=='Edited'


def test_queue_resume_scans_priority_and_changed_book(client,monkeypatch):
    c=client;_,a=account(c,'alice');book=add(c,a)
    c.post('/genre-checks',headers=a)
    with main.db() as db:
        db.execute("UPDATE genre_jobs SET status='checking'")
    initialize(main.db)
    assert c.get('/genre-checks',headers=a).json()['counts']['queued']==1
    from test_backend import jpeg
    c.post('/scans',headers=a,files={'front':('cover.jpg',jpeg(),'image/jpeg')})
    assert run(c) is False
    from test_backend import process
    process(c)
    c.patch('/books/'+book,headers=a,json={'title':'Changed title','author':'Author'})
    async def never(*args,**kwargs):raise AssertionError('Changed metadata must not be classified using the old snapshot')
    monkeypatch.setattr(Scanner,'generate',never)
    assert run(c)
    assert c.get('/genre-checks',headers=a).json()['counts']['failed']==1
    assert c.get('/books',headers=a).json()[0]['genre']==''
