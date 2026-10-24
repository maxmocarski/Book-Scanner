"""Disposable test server: real API/database, fake model/search responses."""
import asyncio
import os
import re
from pathlib import Path
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import api.main as main
from core.scanning import Metadata, Scanner, SecondPass
from core.batch import ShelfPhoto,Spine
from core.genres import Classification
import uvicorn
async def generate(self, model, prompt, schema, images=None):
    await asyncio.sleep(.15)
    if schema is Classification:
        return Classification(genre='Fantasy' if 'Shelf Book' in prompt else 'Fiction')
    if schema is ShelfPhoto:
        count=int(re.search(r'user counted (\d+)',prompt).group(1))
        return ShelfPhoto(books=[Spine(metadata=Metadata(title='Shelf Book '+str(i+1),author='Shelf Author'),left=i/count,right=(i+1)/count) for i in range(count)])
    if schema is Metadata:
        return Metadata(title='The Great Gatsbv', author='F. Sc0tt Fitzgerald', isbn='978O743273565')
    return SecondPass(metadata=Metadata(title='The Great Gatsby', author='F. Scott Fitzgerald', isbn='9780743273565'),
                      reason='OCR spelling corrected', source_indices=[0])
async def search(self, metadata):
    return [{'index':0,'url':'https://example.org/gatsby','title':'The Great Gatsby',
             'content':'F. Scott Fitzgerald ISBN 9780743273565'}], None
if __name__ == '__main__':
    os.environ['BOOKBRIDGE_ADMINS'] = 'manager_ui'
    os.environ.pop('SMTP_HOST', None)
    Scanner.generate = generate
    Scanner.search = search
    with tempfile.TemporaryDirectory(prefix='bookbridge-ui-') as directory:
        main.DATA = Path(directory)
        uvicorn.run(main.app, host='127.0.0.1', port=8765, log_level='warning')

