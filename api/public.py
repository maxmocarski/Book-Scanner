"""Anonymous, read-only access to explicitly public shared-library catalogs."""
from fastapi import Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel
from api import community
from api.mobile import edition_key
from core.shelves import label


class Visibility(BaseModel):
    is_public: bool


def install(app,m):
    def visible(c,identifier):
        row=c.execute('SELECT l.id,l.name FROM libraries l JOIN profiles p ON p.user_id=l.owner WHERE l.id=? AND l.is_public=1 AND p.banned=0',(identifier,)).fetchone()
        if not row:m.fail(404,'Public library not found.')
        return dict(row)

    @app.patch('/libraries/{library_id}/visibility')
    def visibility(library_id:str,body:Visibility,me=Depends(m.user)):
        with m.db() as c:
            community.library_access(c,library_id,me['id'],manage=True)
            c.execute('UPDATE libraries SET is_public=? WHERE id=?',(int(body.is_public),library_id))
        return {'is_public':body.is_public}

    @app.get('/public/libraries')
    def directory(q:str=Query(default='',max_length=100),offset:int=Query(default=0,ge=0)):
        with m.db() as c:
            rows=c.execute("SELECT l.id,l.name,COUNT(b.id) AS books FROM libraries l JOIN profiles p ON p.user_id=l.owner LEFT JOIN books b ON b.library_id=l.id AND b.removed=0 WHERE l.is_public=1 AND p.banned=0 AND instr(lower(l.name),lower(?))>0 GROUP BY l.id ORDER BY l.name COLLATE NOCASE,l.id LIMIT 101 OFFSET ?",(q.strip(),offset)).fetchall()
            return {'libraries':[dict(r) for r in rows[:100]],'next_offset':offset+100 if len(rows)>100 else None}

    @app.get('/public/libraries/{library_id}/books')
    def catalog(library_id:str,q:str=Query(default='',max_length=100),offset:int=Query(default=0,ge=0)):
        with m.db() as c:
            library=visible(c,library_id)
            rows=c.execute("SELECT id,title,author,isbn,shelf,shelf_position,added_order FROM books WHERE library_id=? AND removed=0 AND instr(lower(title||' '||author||' '||COALESCE(isbn,'')||' '||shelf),lower(?))>0 ORDER BY title COLLATE NOCASE,author COLLATE NOCASE,id LIMIT 101 OFFSET ?",(library_id,q.strip(),offset)).fetchall()
            books=[]
            for row in rows[:100]:
                book=dict(row);book['edition_key']=edition_key(row);book['shelf_label']=label(row['shelf'],row['shelf_position'])
                book['images']=[{'view':r['view'],'url':f'/public/libraries/{library_id}/books/{row["id"]}/images/{r["position"]}'} for r in c.execute('SELECT position,view FROM book_images WHERE book_id=? ORDER BY position',(row['id'],))]
                books.append(book)
            return {'library':library,'books':books,'next_offset':offset+100 if len(rows)>100 else None}

    @app.get('/public/libraries/{library_id}/books/{book_id}/images/{position}')
    def image(library_id:str,book_id:str,position:int):
        with m.db() as c:
            visible(c,library_id)
            row=c.execute('SELECT i.image FROM book_images i JOIN books b ON b.id=i.book_id WHERE b.id=? AND b.library_id=? AND b.removed=0 AND i.position=?',(book_id,library_id,position)).fetchone()
            if not row:m.fail(404,'Photo not found.')
        return Response(row['image'],media_type='image/jpeg',headers={'Cache-Control':'no-store'})

    @app.middleware('http')
    async def no_public_cache(request,call_next):
        response=await call_next(request)
        if request.url.path.startswith('/public/'):response.headers['Cache-Control']='no-store'
        return response
