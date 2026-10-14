import asyncio
from contextlib import contextmanager
import json
import sqlite3
import time
import httpx
import pytest
from fastapi.testclient import TestClient
import main
from scanning import Metadata, Scanner, ScanError, SecondPass, baseline
from schema import initialize

def test_isbn_ocr_repair_preserves_digits():
    m,notes,changes=baseline(Metadata(title='1984',author='Orwell',isbn='978O743273565'))
    assert m.isbn=='9780743273565' and m.title=='1984'
    assert any(c['field']=='isbn' for c in changes)
    m,_,_=baseline(Metadata(isbn='9780743273566'));assert m.isbn is None

def test_secondary_cleanup_and_isbn_guard():
    scanner=Scanner(None);calls=[]
    async def generate(model,prompt,schema,images=None):
        calls.append((model,prompt,images))
        return SecondPass(metadata=Metadata(title='The Great Gatsby',author='F. Scott Fitzgerald',isbn='9780306406157'),reason='OCR zero corrected')
    scanner.generate=generate
    m,n,c,s,suggestion=asyncio.run(scanner.enrich(Metadata(title='The Great Gatsbv',author='F. Sc0tt Fitzgerald',isbn='9780743273565'),'cleanup'))
    assert m.title=='The Great Gatsby' and m.author=='F. Scott Fitzgerald' and m.isbn=='9780743273565'
    assert calls[0][0]=='gemma3:1b' and calls[0][2] is None
    assert len([x for x in c if x['source']=='secondary_model'])==2
    assert suggestion is None and s==[] and any('ISBN change was not applied' in x for x in n)

def test_lookup_suggestion_is_separate_and_grounded():
    scanner=Scanner(None)
    async def search(metadata):return [{'index':0,'url':'https://example.org/book','title':'The Great Gatsby — F. Scott Fitzgerald','content':'ISBN 9780743273565 Paperback'}],None
    async def generate(*a,**kw):return SecondPass(metadata=Metadata(title='The Great Gatsby',author='F. Scott Fitzgerald',isbn='9780743273565'),source_indices=[0],reason='Catalog snippet match')
    scanner.search=search;scanner.generate=generate
    m,n,c,s,suggestion=asyncio.run(scanner.enrich(Metadata(title='The Great Gatsby'),'lookup'))
    assert m.author is None and m.isbn is None
    assert suggestion['metadata']['author']=='F. Scott Fitzgerald' and suggestion['metadata']['isbn']=='9780743273565'
    assert suggestion['verified'] is False and len(s)==1
    async def invented(*a,**kw):return SecondPass(metadata=Metadata(title='Invented Different Book',author='Fake Author',isbn='9780306406157'),source_indices=[99])
    scanner.generate=invented
    m,n,c,s,suggestion=asyncio.run(scanner.enrich(Metadata(title='The Great Gatsby'),'lookup'))
    assert m.title=='The Great Gatsby' and m.isbn is None and suggestion is None
    async def uncited(*a,**kw):return SecondPass(metadata=Metadata(title='The Great Gatsby',isbn='9780306406157'),source_indices=[0])
    scanner.generate=uncited
    *_,suggestion=asyncio.run(scanner.enrich(Metadata(title='The Great Gatsby'),'lookup'))
    assert suggestion['metadata']['isbn'] is None

def test_lookup_and_secondary_failures_keep_original():
    scanner=Scanner(None)
    async def search(metadata):return [],'Lookup unavailable; continuing with cleanup.'
    async def unavailable(*a,**kw):raise ScanError('Model missing')
    scanner.search=search;scanner.generate=unavailable
    m,n,c,s,suggestion=asyncio.run(scanner.enrich(Metadata(title='1984',author='George Orwell'),'lookup'))
    assert m.title=='1984' and m.author=='George Orwell'
    assert any('Secondary model unavailable' in x for x in n) and any('Lookup unavailable' in x for x in n)

def test_ollama_and_searxng_payloads(monkeypatch):
    scanner=Scanner(None);seen=[]
    async def post(self,url,json):
        seen.append(json);assert url.endswith('/api/generate')
        if json['model']=='gemma3:12b':
            assert len(json['images'])==3 and json['keep_alive']=='0'
            result={'title':'The Great Gatsbv','author':'F. Sc0tt Fitzgerald','isbn':None}
        else:
            assert 'images' not in json
            result={'metadata':{'title':'The Great Gatsby','author':'F. Scott Fitzgerald','isbn':None},'reason':'OCR typo','source_indices':[0]}
        return httpx.Response(200,json={'response':__import__('json').dumps(result)},request=httpx.Request('POST',url))
    async def get(self,url,params):
        assert url=='http://searxng:8080/search' and params['format']=='json' and 'Gatsbv' in params['q']
        return httpx.Response(200,json={'results':[{'url':'https://example.org/book','title':'The Great Gatsby','content':'F. Scott Fitzgerald'}]},request=httpx.Request('GET',url))
    monkeypatch.setattr(httpx.AsyncClient,'post',post);monkeypatch.setattr(httpx.AsyncClient,'get',get)
    async def pipeline():return await scanner.enrich(await scanner.identify([b'front',b'spine',b'back']),'lookup')
    m,n,c,s,suggestion=asyncio.run(pipeline());assert m.title=='The Great Gatsby' and len(seen)==2 and len(s)==1

def test_searxng_json_disabled_fallback(monkeypatch):
    scanner=Scanner(None)
    async def get(self,url,params):return httpx.Response(403,request=httpx.Request('GET',url))
    monkeypatch.setattr(httpx.AsyncClient,'get',get)
    s,w=asyncio.run(scanner.search(Metadata(title='Some Book')));assert s==[] and 'search.formats includes json' in w

def test_bad_ollama_reply(monkeypatch):
    scanner=Scanner(None)
    async def post(self,url,json):return httpx.Response(200,json={'response':'not json'},request=httpx.Request('POST',url))
    monkeypatch.setattr(httpx.AsyncClient,'post',post)
    with pytest.raises(ScanError):asyncio.run(scanner.identify([b'image']))

def test_migrate_existing_books_and_drafts(tmp_path):
    path=tmp_path/'old.sqlite3';conn=sqlite3.connect(path)
    conn.executescript('''
    CREATE TABLE users(id TEXT PRIMARY KEY,username TEXT UNIQUE,salt TEXT,password_hash TEXT);
    CREATE TABLE books(id TEXT PRIMARY KEY,owner TEXT REFERENCES users(id),title TEXT,author TEXT,isbn TEXT,image BLOB,available INTEGER,created INTEGER);
    CREATE TABLE drafts(id TEXT PRIMARY KEY,owner TEXT REFERENCES users(id),metadata TEXT,image BLOB,expires INTEGER);
    INSERT INTO users VALUES('owner','max','salt','hash');
    INSERT INTO books VALUES('book','owner','Old Title','Old Author',NULL,X'010203',1,1);
    ''')
    conn.execute('INSERT INTO drafts VALUES(?,?,?,?,?)',('draft','owner','{"title":"Draft Title","author":"Author","isbn":null}',b'draft image',int(time.time())+86400))
    conn.execute('INSERT INTO drafts VALUES(?,?,?,?,?)',('expired','owner','{}',b'old',0));conn.commit();conn.close()
    @contextmanager
    def db():
        c=sqlite3.connect(path);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON');c.execute('BEGIN IMMEDIATE')
        try:yield c;c.commit()
        except Exception:c.rollback();raise
        finally:c.close()
    initialize(db);initialize(db)
    with db() as c:
        assert 'image' not in {r['name'] for r in c.execute('PRAGMA table_info(books)')}
        assert c.execute('SELECT title FROM books').fetchone()[0]=='Old Title'
        assert c.execute('SELECT image FROM book_images').fetchone()[0]==b'\x01\x02\x03'
        assert c.execute('SELECT COUNT(*) FROM scans').fetchone()[0]==1
        assert c.execute('SELECT status FROM scans').fetchone()[0]=='ready'
        assert c.execute('SELECT image FROM scan_images').fetchone()[0]==b'draft image'
        assert not c.execute('PRAGMA foreign_key_check').fetchall()
        assert not c.execute("SELECT 1 FROM sqlite_master WHERE name='drafts'").fetchone()

def test_live_background_worker_with_mocked_models(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'DATA',tmp_path);monkeypatch.setattr(main.app.state,'worker_enabled',True,raising=False)
    async def identify(self,images):return Metadata(title='Book',author='Author')
    async def enrich(self,raw,mode):
        m,n,c=baseline(raw);return m,n,c,[],None
    monkeypatch.setattr(Scanner,'identify',identify);monkeypatch.setattr(Scanner,'enrich',enrich)
    with TestClient(main.app) as c:
        r=c.post('/auth/register',json={'username':'reader','password':'testing-password-long'})
        h={'Authorization':'Bearer '+r.json()['access_token']}
        from test_backend import jpeg
        r=c.post('/scans',headers=h,files={'front':('x.jpg',jpeg(),'image/jpeg')});assert r.status_code==202,r.text
        for _ in range(100):
            row=c.get(r.json()['status_url'],headers=h).json()
            if row['status']=='ready':break
            time.sleep(0.02)
        assert row['status']=='ready',row
