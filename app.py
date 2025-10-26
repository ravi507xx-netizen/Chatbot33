from fastapi import FastAPI, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
import secrets
import sqlite3
import hashlib
from datetime import datetime
from typing import Optional
import os

app = FastAPI(
    title="Pollinations Relay API",
    description="Advanced API relay for Pollinations.ai with key management",
    version="2.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database setup
def init_db():
    conn = sqlite3.connect('api_keys.db')
    c = conn.cursor()
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS api_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active BOOLEAN DEFAULT 1,
            requests_count INTEGER DEFAULT 0,
            last_used TIMESTAMP
        )
    ''')
    
    # Default admin: id-mk pass:mk123
    c.execute('''
        CREATE TABLE IF NOT EXISTS admin_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )
    ''')
    
    password_hash = hashlib.sha256("mk123".encode()).hexdigest()
    c.execute('''
        INSERT OR IGNORE INTO admin_users (username, password_hash) 
        VALUES (?, ?)
    ''', ('mk', password_hash))
    
    conn.commit()
    conn.close()

init_db()

# Models
class PollinationsRequest(BaseModel):
    text: str
    api_key: Optional[str] = None

# Utility functions
def generate_api_key():
    return f"pk_{secrets.token_urlsafe(24)}"

def get_db_connection():
    conn = sqlite3.connect('api_keys.db')
    conn.row_factory = sqlite3.Row
    return conn

def verify_admin_password(password: str, stored_hash: str) -> bool:
    return hashlib.sha256(password.encode()).hexdigest() == stored_hash

# Simple session storage
sessions = {}

# API Routes
@app.get("/")
async def root():
    return {
        "status": "success",
        "message": "Hey! What's on your mind? Looking to start a chat, brainstorm something, or just say hi?",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/api")
async def api_info():
    return {
        "service": "Pollinations Relay API",
        "version": "2.0.0",
        "endpoints": {
            "GET /": "Welcome message",
            "GET /api": "API information",
            "POST /prompt": "Send prompt to Pollinations.ai",
            "GET /prompt": "GET version of prompt endpoint",
            "GET /admin": "Admin login",
            "GET /health": "Health check"
        }
    }

@app.post("/prompt")
async def relay_prompt(request: PollinationsRequest):
    if not request.text.strip():
        return {
            "status": "success",
            "message": "Hey! What's on your mind? Looking to start a chat, brainstorm something, or just say hi?",
            "timestamp": datetime.utcnow().isoformat()
        }
    
    if not request.api_key:
        raise HTTPException(status_code=401, detail="API key required")
    
    conn = get_db_connection()
    key_data = conn.execute(
        'SELECT * FROM api_keys WHERE key = ? AND is_active = 1',
        (request.api_key,)
    ).fetchone()
    
    if not key_data:
        conn.close()
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    # Call Pollinations.ai
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(f"https://text.pollinations.ai/prompt/{request.text}")
            response.raise_for_status()
            pollinations_response = response.text
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=f"Pollinations.ai error: {str(e)}")
    
    # Update stats
    conn.execute(
        'UPDATE api_keys SET requests_count = requests_count + 1, last_used = CURRENT_TIMESTAMP WHERE key = ?',
        (request.api_key,)
    )
    conn.commit()
    conn.close()
    
    return {
        "status": "success",
        "message": pollinations_response,
        "data": {
            "original_prompt": request.text,
            "api_key_used": request.api_key[:8] + "..."
        },
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/prompt")
async def relay_prompt_get(text: str, api_key: Optional[str] = None):
    return await relay_prompt(PollinationsRequest(text=text, api_key=api_key))

# Admin Routes
@app.get("/admin", response_class=HTMLResponse)
async def admin_login():
    with open("login.html", "r") as f:
        return HTMLResponse(content=f.read())

@app.post("/admin/login")
async def admin_login_post(username: str = Form(...), password: str = Form(...)):
    conn = get_db_connection()
    admin = conn.execute(
        'SELECT * FROM admin_users WHERE username = ?', 
        (username,)
    ).fetchone()
    conn.close()
    
    if not admin or not verify_admin_password(password, admin['password_hash']):
        with open("login.html", "r") as f:
            html_content = f.read().replace('<!-- ERROR -->', 
                                          '<div class="alert alert-danger">Invalid credentials</div>')
        return HTMLResponse(content=html_content)
    
    # Create session
    session_id = secrets.token_urlsafe(16)
    sessions[session_id] = {"admin_id": admin['id'], "username": admin['username']}
    
    response = RedirectResponse(url="/admin/dashboard", status_code=303)
    response.set_cookie(key="session_id", value=session_id)
    return response

@app.get("/admin/dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    session_id = request.cookies.get("session_id")
    if not session_id or session_id not in sessions:
        return RedirectResponse(url="/admin", status_code=303)
    
    conn = get_db_connection()
    keys = conn.execute('SELECT * FROM api_keys ORDER BY created_at DESC').fetchall()
    total_keys = conn.execute('SELECT COUNT(*) FROM api_keys').fetchone()[0]
    active_keys = conn.execute('SELECT COUNT(*) FROM api_keys WHERE is_active = 1').fetchone()[0]
    total_requests = conn.execute('SELECT SUM(requests_count) FROM api_keys').fetchone()[0] or 0
    conn.close()
    
    with open("admin.html", "r") as f:
        html_content = f.read()
        
        # Replace placeholders with actual data
        html_content = html_content.replace('{{total_keys}}', str(total_keys))
        html_content = html_content.replace('{{active_keys}}', str(active_keys))
        html_content = html_content.replace('{{total_requests}}', str(total_requests))
        
        # Build keys table rows
        keys_html = ""
        for key in keys:
            status_badge = '<span class="badge bg-success">Active</span>' if key['is_active'] else '<span class="badge bg-danger">Inactive</span>'
            last_used = key['last_used'] or 'Never'
            
            keys_html += f"""
            <tr>
                <td>{key['id']}</td>
                <td>{key['name']}</td>
                <td>
                    <code class="api-key">{key['key']}</code>
                    <button class="btn btn-sm btn-outline-secondary copy-btn" data-key="{key['key']}">
                        Copy
                    </button>
                </td>
                <td>{key['created_at']}</td>
                <td>{key['requests_count']}</td>
                <td>{last_used}</td>
                <td>{status_badge}</td>
                <td>
                    <form method="post" action="/admin/keys/{key['id']}/toggle" style="display: inline;">
                        <button type="submit" class="btn btn-sm {'btn-warning' if key['is_active'] else 'btn-success'}">
                            {'Deactivate' if key['is_active'] else 'Activate'}
                        </button>
                    </form>
                    <form method="post" action="/admin/keys/{key['id']}/delete" style="display: inline;" onsubmit="return confirm('Delete this key?')">
                        <button type="submit" class="btn btn-sm btn-danger">Delete</button>
                    </form>
                </td>
            </tr>
            """
        
        html_content = html_content.replace('<!-- KEYS_TABLE -->', keys_html)
        
    return HTMLResponse(content=html_content)

@app.post("/admin/keys/create")
async def create_api_key(request: Request, name: str = Form(...)):
    session_id = request.cookies.get("session_id")
    if not session_id or session_id not in sessions:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    new_key = generate_api_key()
    conn = get_db_connection()
    conn.execute('INSERT INTO api_keys (key, name) VALUES (?, ?)', (new_key, name))
    conn.commit()
    conn.close()
    
    return RedirectResponse(url="/admin/dashboard", status_code=303)

@app.post("/admin/keys/{key_id}/toggle")
async def toggle_api_key(key_id: int, request: Request):
    session_id = request.cookies.get("session_id")
    if not session_id or session_id not in sessions:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    conn = get_db_connection()
    key = conn.execute('SELECT * FROM api_keys WHERE id = ?', (key_id,)).fetchone()
    if key:
        conn.execute('UPDATE api_keys SET is_active = ? WHERE id = ?', (not key['is_active'], key_id))
        conn.commit()
    conn.close()
    
    return RedirectResponse(url="/admin/dashboard", status_code=303)

@app.post("/admin/keys/{key_id}/delete")
async def delete_api_key(key_id: int, request: Request):
    session_id = request.cookies.get("session_id")
    if not session_id or session_id not in sessions:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    conn = get_db_connection()
    conn.execute('DELETE FROM api_keys WHERE id = ?', (key_id,))
    conn.commit()
    conn.close()
    
    return RedirectResponse(url="/admin/dashboard", status_code=303)

@app.get("/admin/logout")
async def admin_logout():
    response = RedirectResponse(url="/admin", status_code=303)
    response.delete_cookie(key="session_id")
    return response

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "pollinations-relay", "timestamp": datetime.utcnow().isoformat()}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)            name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active BOOLEAN DEFAULT 1,
            requests_count INTEGER DEFAULT 0,
            last_used TIMESTAMP
        )
    ''')
    
    # Default admin: id-mk pass:mk123
    c.execute('''
        CREATE TABLE IF NOT EXISTS admin_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )
    ''')
    
    password_hash = hashlib.sha256("mk123".encode()).hexdigest()
    c.execute('''
        INSERT OR IGNORE INTO admin_users (username, password_hash) 
        VALUES (?, ?)
    ''', ('mk', password_hash))
    
    conn.commit()
    conn.close()

init_db()

# Models
class PollinationsRequest(BaseModel):
    text: str
    api_key: Optional[str] = None

# Utility functions
def generate_api_key():
    return f"pk_{secrets.token_urlsafe(24)}"

def get_db_connection():
    conn = sqlite3.connect('api_keys.db')
    conn.row_factory = sqlite3.Row
    return conn

def verify_admin_password(password: str, stored_hash: str) -> bool:
    return hashlib.sha256(password.encode()).hexdigest() == stored_hash

# Simple session storage
sessions = {}

# API Routes
@app.get("/")
async def root():
    return {
        "status": "success",
        "message": "Hey! What's on your mind? Looking to start a chat, brainstorm something, or just say hi?",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.post("/prompt")
async def relay_prompt(request: PollinationsRequest):
    if not request.text.strip():
        return {
            "status": "success",
            "message": "Hey! What's on your mind? Looking to start a chat, brainstorm something, or just say hi?",
            "timestamp": datetime.utcnow().isoformat()
        }
    
    if not request.api_key:
        raise HTTPException(status_code=401, detail="API key required")
    
    conn = get_db_connection()
    key_data = conn.execute(
        'SELECT * FROM api_keys WHERE key = ? AND is_active = 1',
        (request.api_key,)
    ).fetchone()
    
    if not key_data:
        conn.close()
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    # Call Pollinations.ai
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(f"https://text.pollinations.ai/prompt/{request.text}")
            response.raise_for_status()
            pollinations_response = response.text
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=f"Pollinations.ai error: {str(e)}")
    
    # Update stats
    conn.execute(
        'UPDATE api_keys SET requests_count = requests_count + 1, last_used = CURRENT_TIMESTAMP WHERE key = ?',
        (request.api_key,)
    )
    conn.commit()
    conn.close()
    
    return {
        "status": "success",
        "message": pollinations_response,
        "data": {
            "original_prompt": request.text,
            "api_key_used": request.api_key[:8] + "..."
        },
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/prompt")
async def relay_prompt_get(text: str, api_key: Optional[str] = None):
    return await relay_prompt(PollinationsRequest(text=text, api_key=api_key))

# Admin Routes
@app.get("/admin", response_class=HTMLResponse)
async def admin_login():
    with open("login.html", "r") as f:
        return HTMLResponse(content=f.read())

@app.post("/admin/login")
async def admin_login_post(request: Request, username: str = Form(...), password: str = Form(...)):
    conn = get_db_connection()
    admin = conn.execute(
        'SELECT * FROM admin_users WHERE username = ?', 
        (username,)
    ).fetchone()
    conn.close()
    
    if not admin or not verify_admin_password(password, admin['password_hash']):
        with open("login.html", "r") as f:
            html_content = f.read().replace('<!-- ERROR -->', 
                                          '<div class="alert alert-danger">Invalid credentials</div>')
        return HTMLResponse(content=html_content)
    
    # Create session
    session_id = secrets.token_urlsafe(16)
    sessions[session_id] = {"admin_id": admin['id'], "username": admin['username']}
    
    response = RedirectResponse(url="/admin/dashboard", status_code=303)
    response.set_cookie(key="session_id", value=session_id)
    return response

@app.get("/admin/dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    session_id = request.cookies.get("session_id")
    if not session_id or session_id not in sessions:
        return RedirectResponse(url="/admin", status_code=303)
    
    conn = get_db_connection()
    keys = conn.execute('SELECT * FROM api_keys ORDER BY created_at DESC').fetchall()
    total_keys = conn.execute('SELECT COUNT(*) FROM api_keys').fetchone()[0]
    active_keys = conn.execute('SELECT COUNT(*) FROM api_keys WHERE is_active = 1').fetchone()[0]
    total_requests = conn.execute('SELECT SUM(requests_count) FROM api_keys').fetchone()[0] or 0
    conn.close()
    
    with open("admin.html", "r") as f:
        html_content = f.read()
        
        # Replace placeholders with actual data
        html_content = html_content.replace('{{total_keys}}', str(total_keys))
        html_content = html_content.replace('{{active_keys}}', str(active_keys))
        html_content = html_content.replace('{{total_requests}}', str(total_requests))
        
        # Build keys table rows
        keys_html = ""
        for key in keys:
            status_badge = '<span class="badge bg-success">Active</span>' if key['is_active'] else '<span class="badge bg-danger">Inactive</span>'
            last_used = key['last_used'] or 'Never'
            
            keys_html += f"""
            <tr>
                <td>{key['id']}</td>
                <td>{key['name']}</td>
                <td>
                    <code class="api-key">{key['key']}</code>
                    <button class="btn btn-sm btn-outline-secondary copy-btn" data-key="{key['key']}">
                        Copy
                    </button>
                </td>
                <td>{key['created_at']}</td>
                <td>{key['requests_count']}</td>
                <td>{last_used}</td>
                <td>{status_badge}</td>
                <td>
                    <form method="post" action="/admin/keys/{key['id']}/toggle" style="display: inline;">
                        <button type="submit" class="btn btn-sm {'btn-warning' if key['is_active'] else 'btn-success'}">
                            {'Deactivate' if key['is_active'] else 'Activate'}
                        </button>
                    </form>
                    <form method="post" action="/admin/keys/{key['id']}/delete" style="display: inline;" onsubmit="return confirm('Delete this key?')">
                        <button type="submit" class="btn btn-sm btn-danger">Delete</button>
                    </form>
                </td>
            </tr>
            """
        
        html_content = html_content.replace('<!-- KEYS_TABLE -->', keys_html)
        
    return HTMLResponse(content=html_content)

@app.post("/admin/keys/create")
async def create_api_key(request: Request, name: str = Form(...)):
    session_id = request.cookies.get("session_id")
    if not session_id or session_id not in sessions:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    new_key = generate_api_key()
    conn = get_db_connection()
    conn.execute('INSERT INTO api_keys (key, name) VALUES (?, ?)', (new_key, name))
    conn.commit()
    conn.close()
    
    return RedirectResponse(url="/admin/dashboard", status_code=303)

@app.post("/admin/keys/{key_id}/toggle")
async def toggle_api_key(key_id: int, request: Request):
    session_id = request.cookies.get("session_id")
    if not session_id or session_id not in sessions:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    conn = get_db_connection()
    key = conn.execute('SELECT * FROM api_keys WHERE id = ?', (key_id,)).fetchone()
    if key:
        conn.execute('UPDATE api_keys SET is_active = ? WHERE id = ?', (not key['is_active'], key_id))
        conn.commit()
    conn.close()
    
    return RedirectResponse(url="/admin/dashboard", status_code=303)

@app.post("/admin/keys/{key_id}/delete")
async def delete_api_key(key_id: int, request: Request):
    session_id = request.cookies.get("session_id")
    if not session_id or session_id not in sessions:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    conn = get_db_connection()
    conn.execute('DELETE FROM api_keys WHERE id = ?', (key_id,))
    conn.commit()
    conn.close()
    
    return RedirectResponse(url="/admin/dashboard", status_code=303)

@app.get("/admin/logout")
async def admin_logout():
    response = RedirectResponse(url="/admin", status_code=303)
    response.delete_cookie(key="session_id")
    return response

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "pollinations-relay", "timestamp": datetime.utcnow().isoformat()}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)    # API keys table
    c.execute('''
        CREATE TABLE IF NOT EXISTS api_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active BOOLEAN DEFAULT 1,
            requests_count INTEGER DEFAULT 0,
            last_used TIMESTAMP
        )
    ''')
    
    # Admin credentials (id: mk, pass: mk123)
    c.execute('''
        CREATE TABLE IF NOT EXISTS admin_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )
    ''')
    
    # Insert default admin if not exists
    password_hash = hashlib.sha256("mk123".encode()).hexdigest()
    c.execute('''
        INSERT OR IGNORE INTO admin_users (username, password_hash) 
        VALUES (?, ?)
    ''', ('mk', password_hash))
    
    conn.commit()
    conn.close()

init_db()

# Pydantic models
class APIKeyCreate(BaseModel):
    name: str

class APIKeyResponse(BaseModel):
    id: int
    key: str
    name: str
    created_at: str
    is_active: bool
    requests_count: int
    last_used: Optional[str]

class PollinationsRequest(BaseModel):
    text: str
    api_key: Optional[str] = None

class StandardResponse(BaseModel):
    status: str
    message: str
    data: Optional[Dict] = None
    timestamp: str

# Pollinations.ai API base URL
POLLINATIONS_BASE_URL = "https://text.pollinations.ai/prompt"

# In-memory rate limiting (for demo - use Redis in production)
rate_limits = {}

# Utility functions
def generate_api_key():
    return f"pk_{secrets.token_urlsafe(32)}"

def verify_admin_password(password: str, stored_hash: str) -> bool:
    return hashlib.sha256(password.encode()).hexdigest() == stored_hash

def get_db_connection():
    conn = sqlite3.connect('api_keys.db')
    conn.row_factory = sqlite3.Row
    return conn

def check_rate_limit(api_key: str, limit: int = 100, window: int = 3600):
    """Basic rate limiting"""
    current_time = time.time()
    if api_key not in rate_limits:
        rate_limits[api_key] = []
    
    # Clean old requests
    rate_limits[api_key] = [t for t in rate_limits[api_key] if current_time - t < window]
    
    if len(rate_limits[api_key]) >= limit:
        return False
    
    rate_limits[api_key].append(current_time)
    return True

# Admin authentication
def get_current_admin(request: Request):
    admin_id = request.session.get('admin_id')
    if not admin_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return admin_id

# API Routes
@app.get("/")
async def root():
    return StandardResponse(
        status="success",
        message="Hey! What's on your mind? Looking to start a chat, brainstorm something, or just say hi?",
        timestamp=datetime.utcnow().isoformat()
    )

@app.post("/prompt")
async def relay_prompt(request: PollinationsRequest):
    """
    Relay prompt to Pollinations.ai API with API key authentication
    """
    # Welcome message for empty prompts
    if not request.text.strip():
        return StandardResponse(
            status="success",
            message="Hey! What's on your mind? Looking to start a chat, brainstorm something, or just say hi?",
            timestamp=datetime.utcnow().isoformat()
        )
    
    # API key validation
    if not request.api_key:
        raise HTTPException(status_code=401, detail="API key required")
    
    conn = get_db_connection()
    key_data = conn.execute(
        'SELECT * FROM api_keys WHERE key = ? AND is_active = 1',
        (request.api_key,)
    ).fetchone()
    conn.close()
    
    if not key_data:
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    # Rate limiting
    if not check_rate_limit(request.api_key):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    
    # Fetch from Pollinations.ai
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(f"{POLLINATIONS_BASE_URL}/{request.text}")
            response.raise_for_status()
            pollinations_response = response.text
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pollinations.ai error: {str(e)}")
    
    # Update usage stats
    conn = get_db_connection()
    conn.execute(
        'UPDATE api_keys SET requests_count = requests_count + 1, last_used = CURRENT_TIMESTAMP WHERE key = ?',
        (request.api_key,)
    )
    conn.commit()
    conn.close()
    
    return StandardResponse(
        status="success",
        message=pollinations_response,
        data={
            "original_prompt": request.text,
            "api_key_used": request.api_key[:8] + "..." if request.api_key else None
        },
        timestamp=datetime.utcnow().isoformat()
    )

@app.get("/prompt")
async def relay_prompt_get(text: str, api_key: Optional[str] = None):
    """GET endpoint for prompt relay"""
    return await relay_prompt(PollinationsRequest(text=text, api_key=api_key))

# Admin Panel Routes
@app.get("/admin", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/admin/login")
async def admin_login(request: Request, username: str = Form(...), password: str = Form(...)):
    conn = get_db_connection()
    admin = conn.execute(
        'SELECT * FROM admin_users WHERE username = ?', 
        (username,)
    ).fetchone()
    conn.close()
    
    if not admin or not verify_admin_password(password, admin['password_hash']):
        return templates.TemplateResponse("login.html", {
            "request": request, 
            "error": "Invalid credentials"
        })
    
    # Create session (simple implementation)
    request.session['admin_id'] = admin['id']
    return RedirectResponse("/admin/dashboard", status_code=303)

@app.get("/admin/dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    if not request.session.get('admin_id'):
        return RedirectResponse("/admin", status_code=303)
    
    conn = get_db_connection()
    
    # Get all API keys
    keys = conn.execute('''
        SELECT * FROM api_keys ORDER BY created_at DESC
    ''').fetchall()
    
    # Get stats
    total_keys = conn.execute('SELECT COUNT(*) FROM api_keys').fetchone()[0]
    active_keys = conn.execute('SELECT COUNT(*) FROM api_keys WHERE is_active = 1').fetchone()[0]
    total_requests = conn.execute('SELECT SUM(requests_count) FROM api_keys').fetchone()[0] or 0
    
    conn.close()
    
    return templates.TemplateResponse("admin.html", {
        "request": request,
        "keys": keys,
        "total_keys": total_keys,
        "active_keys": active_keys,
        "total_requests": total_requests
    })

@app.post("/admin/keys/create")
async def create_api_key(request: Request, name: str = Form(...)):
    if not request.session.get('admin_id'):
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    new_key = generate_api_key()
    
    conn = get_db_connection()
    try:
        conn.execute(
            'INSERT INTO api_keys (key, name) VALUES (?, ?)',
            (new_key, name)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="Key generation failed, try again")
    
    conn.close()
    return RedirectResponse("/admin/dashboard", status_code=303)

@app.post("/admin/keys/{key_id}/toggle")
async def toggle_api_key(key_id: int, request: Request):
    if not request.session.get('admin_id'):
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    conn = get_db_connection()
    key = conn.execute('SELECT * FROM api_keys WHERE id = ?', (key_id,)).fetchone()
    if not key:
        conn.close()
        raise HTTPException(status_code=404, detail="Key not found")
    
    conn.execute(
        'UPDATE api_keys SET is_active = ? WHERE id = ?',
        (not key['is_active'], key_id)
    )
    conn.commit()
    conn.close()
    
    return RedirectResponse("/admin/dashboard", status_code=303)

@app.post("/admin/keys/{key_id}/delete")
async def delete_api_key(key_id: int, request: Request):
    if not request.session.get('admin_id'):
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    conn = get_db_connection()
    conn.execute('DELETE FROM api_keys WHERE id = ?', (key_id,))
    conn.commit()
    conn.close()
    
    return RedirectResponse("/admin/dashboard", status_code=303)

@app.get("/admin/keys/search")
async def search_keys(request: Request, q: str = ""):
    if not request.session.get('admin_id'):
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    conn = get_db_connection()
    keys = conn.execute('''
        SELECT * FROM api_keys 
        WHERE name LIKE ? OR key LIKE ?
        ORDER BY created_at DESC
    ''', (f'%{q}%', f'%{q}%')).fetchall()
    conn.close()
    
    return [dict(key) for key in keys]

@app.get("/admin/logout")
async def admin_logout(request: Request):
    request.session.clear()
    return RedirectResponse("/admin", status_code=303)

@app.get("/health")
async def health_check():
    return StandardResponse(
        status="healthy",
        message="Service is running smoothly",
        timestamp=datetime.utcnow().isoformat()
    )

# Session middleware (simple in-memory implementation)
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
app.add_middleware(HTTPSRedirectMiddleware)

# Simple session storage
from starlette.middleware.sessions import SessionMiddleware
app.add_middleware(SessionMiddleware, secret_key="your-secret-key-change-in-production")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
