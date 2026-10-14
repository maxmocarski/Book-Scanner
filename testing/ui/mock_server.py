"""Disposable test server: real API/database, fake model/search responses."""
import asyncio
from pathlib import Path
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import main
from scanning import Metadata, Scanner, SecondPass
import uvicorn

async def generate(self, model, prompt, schema, images=None):
    await asyncio.sleep(.15)
    if schema is Metadata:
        return Metadata(title='The Great Gatsbv', author='F. Sc0tt Fitzgerald', isbn='978O743273565')
    return SecondPass(metadata=Metadata(title='The Great Gatsby', author='F. Scott Fitzgerald', isbn='9780743273565'),
                      reason='OCR spelling corrected', source_indices=[0])

async def search(self, metadata):
    return [{'index':0,'url':'https://example.org/gatsby','title':'The Great Gatsby',
             'content':'F. Scott Fitzgerald ISBN 9780743273565'}], None

if __name__ == '__main__':
    Scanner.generate = generate
    Scanner.search = search
    with tempfile.TemporaryDirectory(prefix='bookbridge-ui-') as directory:
        main.DATA = Path(directory)
        uvicorn.run(main.app, host='127.0.0.1', port=8765, log_level='warning')
