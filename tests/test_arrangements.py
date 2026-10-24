from test_backend import client, account, add
from api import main
from core.scanning import Scanner


def test_genre_lookup_permissions_and_preserved_custom_number(client, monkeypatch):
    c=client;_,a=account(c,'alice');_,b=account(c,'other')
    identifier=add(c,a)
    book=c.get('/books',headers=a).json()[0]
    body={k:book[k] for k in ('title','author','isbn')}
    changed=c.patch('/books/'+identifier,headers=a,json={**body,'genre':'History','shelf':'Shelf 2','shelf_position':42})
    assert changed.status_code==200,changed.text
    assert changed.json()['shelf_position']==42
    assert c.post('/books/'+identifier+'/genre',headers=b).status_code==404
    async def search(self,metadata):return [{'title':metadata.title,'content':'Literary fiction','url':'https://example.com'}],None
    async def generate(self,model,prompt,schema,images=None):return schema(genre='Literary fiction')
    monkeypatch.setattr(Scanner,'search',search);monkeypatch.setattr(Scanner,'generate',generate)
    result=c.post('/books/'+identifier+'/genre',headers=a)
    assert result.status_code==200,result.text
    assert result.json()['genre']=='Literary fiction'
    assert result.json()['shelf_position']==42 and result.json()['shelf']=='Shelf 2'
    preserved=c.patch('/books/'+identifier,headers=a,json=body).json()
    assert preserved['genre']=='Literary fiction' and preserved['shelf_position']==42
    assert c.patch('/books/'+identifier,headers=a,json={**body,'shelf_position':0}).status_code==422
    async def unavailable(self,metadata):return [],'Unavailable'
    monkeypatch.setattr(Scanner,'search',unavailable)
    assert c.post('/books/'+identifier+'/genre',headers=a).status_code==503
    assert c.get('/books',headers=a).json()[0]['genre']=='Literary fiction'
