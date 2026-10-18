from test_backend import client, account, add, jpeg, process
from api import main,community


def test_public_catalog_visibility_permissions_and_photo_revocation(client,monkeypatch):
    c=client;monkeypatch.setenv('BOOKBRIDGE_ADMINS','manager');_,admin=account(c,'manager');_,member=account(c,'reader');_,other=account(c,'outsider')
    lib=c.post('/libraries',headers=admin,json={'name':'School'}).json()['id']
    c.post('/libraries/'+lib+'/members',headers=admin,json={'username':'reader'})
    personal=add(c,admin)
    scan=c.post('/scans',headers=member,data={'library_id':lib,'shelf':'Shelf A'},files={'front':('cover.jpg',jpeg(),'image/jpeg')}).json();process(c)
    book=c.post(scan['status_url']+'/save',headers=member,json={'title':'Shared book','author':'A. Reader','isbn':None}).json()['book_id']
    path='/public/libraries/'+lib+'/books'
    photo=path+'/'+book+'/images/0'
    assert c.get('/public/libraries').json()['libraries']==[]
    assert c.get(path).status_code==404 and c.get(photo).status_code==404
    assert c.patch('/libraries/'+lib+'/visibility',json={'is_public':True}).status_code in (401,403)
    assert c.patch('/libraries/'+lib+'/visibility',headers=member,json={'is_public':True}).status_code==403
    assert c.patch('/libraries/'+lib+'/visibility',headers=other,json={'is_public':True}).status_code==404
    assert c.patch('/libraries/'+lib+'/visibility',headers=admin,json={'is_public':True}).status_code==200
    directory=c.get('/public/libraries');assert directory.headers['cache-control']=='no-store'
    assert directory.json()['libraries']==[{'id':lib,'name':'School','books':1}]
    assert c.get('/public/libraries?q=missing').json()['libraries']==[]
    result=c.get(path).json();assert result['library']=={'id':lib,'name':'School'}
    assert len(result['books'])==1 and result['books'][0]['id']==book
    row=result['books'][0];assert row['shelf_label']=='Shelf A (1)'
    assert not {'owner','scan_audit','available','library_id'} & row.keys()
    assert c.get(path+'?q=Shared').json()['books'][0]['id']==book
    assert c.get(path+'?q=notfound').json()['books']==[]
    assert c.get(photo).status_code==200 and c.get(photo).headers['cache-control']=='no-store'
    assert c.get(path+'/'+personal+'/images/0').status_code==404
    assert c.get('/books').status_code in (401,403)
    assert c.get('/libraries/'+lib+'/members').status_code in (401,403)
    assert c.get('/libraries/'+lib+'/export.csv').status_code in (401,403)
    assert c.get('/scans').status_code in (401,403)
    assert c.patch('/books/'+book,json={'title':'edit','author':'x'}).status_code in (401,403)
    assert c.delete('/books/'+book).status_code in (401,403)
    assert c.get('/public/libraries/'+lib+'/books',headers=other).status_code==200
    assert c.patch('/libraries/'+lib+'/visibility',headers=admin,json={'is_public':False}).status_code==200
    assert c.get(photo).status_code==404 and c.get(path).status_code==404
    assert c.get('/public/libraries').json()['libraries']==[]
    # Public status survives restarts; banned owners disappear from the directory.
    c.patch('/libraries/'+lib+'/visibility',headers=admin,json={'is_public':True})
    community.initialize(main.db)
    assert c.get(path).status_code==200
    with main.db() as db:db.execute("UPDATE profiles SET banned=1 WHERE user_id=(SELECT owner FROM libraries WHERE id=?)",(lib,))
    assert c.get(photo).status_code==404 and c.get('/public/libraries').json()['libraries']==[]


def test_public_creation_defaults_and_catalog_pagination(client,monkeypatch):
    c=client;monkeypatch.setenv('BOOKBRIDGE_ADMINS','manager');_,admin=account(c,'manager')
    private=c.post('/libraries',headers=admin,json={'name':'Private'}).json()['id']
    public=c.post('/libraries',headers=admin,json={'name':'Public','is_public':True}).json()['id']
    listed=c.get('/libraries',headers=admin).json()
    assert {r['id']:r['is_public'] for r in listed}=={private:0,public:1}
    owner=c.get('/me',headers=admin).json()['id']
    with main.db() as db:
        for n in range(102):
            db.execute('INSERT INTO books(id,owner,title,author,created,library_id,removed) VALUES(?,?,?,?,?,?,?)',(str(n),owner,'Book '+str(n).zfill(3),'Author',1,public,int(n==101)))
    path='/public/libraries/'+public+'/books'
    first=c.get(path).json();second=c.get(path+'?offset=100').json()
    assert len(first['books'])==100 and first['next_offset']==100
    assert len(second['books'])==1 and second['next_offset'] is None
    assert len({b['id'] for b in first['books']+second['books']})==101
    assert c.get(path+'?offset=-1').status_code==422
    assert c.get(path+'?q='+'a'*101).status_code==422
