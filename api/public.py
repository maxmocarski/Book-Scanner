"""Anonymous, read-only access to explicitly public shared-library catalogs."""
import re
from functools import lru_cache
from fastapi import Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel
from api import community
from api.mobile import edition_key
from core.shelves import label


@lru_cache(maxsize=1024)
def shelf_order(name):
    name=name.strip().casefold()
    parts=re.split(r'(\d+)',name)
    return tuple(int(part) if i % 2 else part for i,part in enumerate(parts)),name


def compare_shelves(left,right):
    a,b=shelf_order(left),shelf_order(right)
    return (a>b)-(a<b)


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
    def catalog(library_id:str, q:str=Query(default='',max_length=100),
                offset:int=Query(default=0,ge=0), limit:int=Query(default=100,ge=1,le=250)):
        with m.db() as c:
            library=visible(c,library_id)
            where='WHERE library_id=? AND removed=0'
            params=[library_id]
            if q.strip():
                where+=" AND instr(lower(title||' '||author||' '||COALESCE(isbn,'')||' '||shelf),lower(?))>0"
                params.append(q.strip())
            total=c.execute('SELECT COUNT(*) FROM books '+where,params).fetchone()[0]
            c.create_collation('SHELF_ORDER',compare_shelves)
            rows=c.execute('SELECT id,title,author,isbn,shelf,shelf_position,added_order FROM books '+where+
                           """ ORDER BY trim(shelf)='', shelf COLLATE SHELF_ORDER,
                               CASE WHEN trim(shelf)<>'' THEN shelf_position IS NULL END,
                               CASE WHEN trim(shelf)<>'' THEN shelf_position END,
                               added_order,title COLLATE NOCASE,author COLLATE NOCASE,id LIMIT ? OFFSET ?""",
                           [*params,limit,offset]).fetchall()
            books=[]
            by_id={}
            for row in rows:
                book=dict(row)
                book.update(edition_key=edition_key(row),shelf_label=label(row['shelf'],row['shelf_position']),images=[])
                books.append(book)
                by_id[row['id']]=book
            if by_id:
                slots=','.join('?' for _ in by_id)
                for image in c.execute(f'SELECT book_id,position,view FROM book_images WHERE book_id IN ({slots}) ORDER BY book_id,position',list(by_id)):
                    book_id=image['book_id']
                    by_id[book_id]['images'].append({'view':image['view'],'url':f'/public/libraries/{library_id}/books/{book_id}/images/{image["position"]}'})
            return {'library':library,'books':books,'total':total,'next_offset':offset+limit if offset+limit<total else None}

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
