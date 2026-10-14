import json
import base64
import sqlite3
import requests
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

app = FastAPI(title="ShelfScan — Book Catalog AI")

DB_PATH = "/data/books.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            author TEXT,
            isbn TEXT,
            summary TEXT,
            cover_image TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

init_db()

OLLAMA_URL = "http://localhost:11434/api/generate"
VISION_MODEL = "gemma3:12b"  # Your preferred local vision model
SUMMARY_MODEL = "llama3.2:3b" # Smaller model for lightweight summaries

def query_ollama_vision(images_b64: List[str]) -> Dict[str, Any]:
    prompt = (
        "Analyze the provided image of a book cover, spine, or barcode. "
        "Carefully read the title, author's name, and any visible ISBN number. "
        "Return your answer strictly as a JSON object with these exact keys: "
        '{"title": "...", "author": "...", "isbn": "..."}'
    )
    payload = {
        "model": VISION_MODEL,
        "prompt": prompt,
        "images": images_b64,
        "stream": False,
        # Removed "format": "json" temporarily so the model doesn't lock up if it adds conversational text, 
        # and let our parser handle cleaning it up.
    }
    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=60)
        response.raise_for_status()
        raw_text = response.json().get("response", "{}")

        # Clean up markdown code blocks if the model includes them
        clean_str = raw_text.replace("```json", "").replace("```", "").strip()
        start_idx = clean_str.find("{")
        end_idx = clean_str.rfind("}")
        if start_idx != -1 and end_idx != -1:
            json_str = clean_str[start_idx:end_idx+1]
            return json.loads(json_str)
        return json.loads(clean_str)
    except Exception as e:
        print(f"Vision error: {e}")
        return {"title": "Unknown Book", "author": "Unknown Author", "isbn": "N/A"}

def generate_summary(title: str, author: str) -> str:
    prompt = f"Provide a brief, 2-3 sentence engaging summary or plot overview for the book '{title}' by {author}."
    payload = {
        "model": SUMMARY_MODEL,
        "prompt": prompt,
        "stream": False
    }
    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=30)
        response.raise_for_status()
        return response.json().get("response", "Summary unavailable.").strip()
    except Exception as e:
        print(f"Summary error: {e}")
        return "Summary could not be generated."

@app.post("/api/scan-queue")
async def scan_queue(files: List[UploadFile] = File(...)):
    images_b64 = []
    for f in files:
        contents = await f.read()
        images_b64.append(base64.b64encode(contents).decode('utf-8'))
    
    # Use the first image as the stored cover image data URI
    cover_uri = f"data:image/jpeg;base64,{images_b64[0]}"
    
    metadata = query_ollama_vision(images_b64)
    title = metadata.get("title", "Unknown Book")
    author = metadata.get("author", "Unknown Author")
    isbn = metadata.get("isbn", "N/A")
    
    summary = generate_summary(title, author)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO books (title, author, isbn, summary, cover_image) VALUES (?, ?, ?, ?, ?)",
        (title, author, isbn, summary, cover_uri)
    )
    conn.commit()
    book_id = cursor.lastrowid
    conn.close()
    
    return {
        "id": book_id,
        "title": title,
        "author": author,
        "isbn": isbn,
        "summary": summary,
        "cover_image": cover_uri
    }

@app.get("/api/books")
async def get_books():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM books ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

@app.put("/api/books/{book_id}/cover")
async def update_cover(book_id: int, file: UploadFile = File(...)):
    contents = await file.read()
    new_cover_uri = f"data:image/jpeg;base64,{base64.b64encode(contents).decode('utf-8')}"
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE books SET cover_image = ? WHERE id = ?", (new_cover_uri, book_id))
    conn.commit()
    conn.close()
    return {"status": "success", "cover_image": new_cover_uri}

@app.get("/api/export")
async def export_json():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM books")
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return JSONResponse(content=rows)

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def read_index():
    return FileResponse("static/index.html")
