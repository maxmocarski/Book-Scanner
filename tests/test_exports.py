import csv
import io
from test_backend import client, account, jpeg, process
from api import main


def test_library_csv_scope_copies_encoding_and_access(client,monkeypatch):
    c=client;monkeypatch.setenv('BOOKBRIDGE_ADMINS','manager');_,admin=account(c,'manager');_,member=account(c,'reader');_,other=account(c,'outsider')
    lib=c.post('/libraries',headers=admin,json={'name':'Town library'}).json()['id']
    c.post('/libraries/'+lib+'/members',headers=admin,json={'username':'reader'})
    path='/libraries/'+lib+'/export.csv'
    assert c.get(path).status_code in (401,403)
    assert c.get(path,headers=other).status_code==404
    assert list(csv.reader(io.StringIO(c.get(path,headers=member).content.decode('utf-8-sig'))))==[['Title','Author','ISBN','Shelf']]
    for title,shelf,library in [('Polish, English\nStories','Żółta półka',lib),('Polish, English\nStories','A2',lib),('Personal book','Private','')]:
        scan=c.post('/scans',headers=admin,data={'library_id':library,'shelf':shelf},files={'front':('cover.jpg',jpeg(),'image/jpeg')}).json()
        process(c)
        saved=c.post(scan['status_url']+'/save',headers=admin,json={'title':title,'author':'A. Writer','isbn':None}).json()
    # Ready scans are not catalog entries; removed books are excluded too.
    c.post('/scans',headers=admin,data={'library_id':lib},files={'front':('cover.jpg',jpeg(),'image/jpeg')});process(c)
    response=c.get(path,headers=member)
    assert response.status_code==200 and response.headers['cache-control']=='no-store'
    assert response.headers['content-disposition'].startswith('attachment;')
    assert response.content.startswith(b'\xef\xbb\xbf')
    rows=list(csv.reader(io.StringIO(response.content.decode('utf-8-sig'))))
    assert rows[0]==['Title','Author','ISBN','Shelf'] and len(rows)==3
    assert {r[3] for r in rows[1:]}=={'Żółta półka (1)','A2 (1)'}
    assert all(r[0]=='Polish, English\nStories' and r[2]=='' for r in rows[1:])
    with main.db() as db:
        db.execute("UPDATE books SET title='=1+1',author=' @SUM(1)',shelf=char(9)||'label' WHERE library_id=? AND shelf='A2'",(lib,))
        db.execute("UPDATE books SET removed=1 WHERE library_id=? AND shelf<>'A2' AND title<>'=1+1'",(lib,))
    rows=list(csv.reader(io.StringIO(c.get(path,headers=admin).content.decode('utf-8-sig'))))
    assert len(rows)==2 and rows[1]==["'=1+1","' @SUM(1)",'',"'\tlabel (1)"]
    uid=c.get('/me',headers=member).json()['id']
    c.delete('/libraries/'+lib+'/members/'+uid,headers=admin)
    assert c.get(path,headers=member).status_code==404
