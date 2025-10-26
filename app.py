from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import httpx
import asyncio
from typing import Optional

app = FastAPI(title="Pollinations Relay API", version="1.0.0")

# Configure CORS to allow requests from any origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pollinations.ai API base URL
POLLINATIONS_BASE_URL = "https://text.pollinations.ai/prompt"

async def fetch_pollinations_response(text: str, timeout: float = 30.0) -> str:
    """
    Fetch response from Pollinations.ai API with error handling and timeout
    """
    url = f"{POLLINATIONS_BASE_URL}/{text}"
    
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url)
            response.raise_for_status()  # Raises exception for 4xx/5xx status codes
            return response.text
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Request to Pollinations.ai timed out")
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Pollinations.ai returned error: {e.response.status_code} {e.response.text}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Unexpected error contacting Pollinations.ai: {str(e)}"
        )

@app.get("/")
async def root():
    return {
        "message": "Pollinations Relay API is running!",
        "usage": "GET /prompt?text=Your+text+here",
        "documentation": "Visit /docs for API documentation"
    }

@app.get("/prompt")
async def relay_prompt(text: str, timeout: Optional[float] = 30.0):
    """
    Relay prompt to Pollinations.ai API and return the response
    
    Args:
        text: The text prompt to send to Pollinations.ai
        timeout: Request timeout in seconds (default: 30.0)
    
    Returns:
        The response from Pollinations.ai API
    """
    if not text.strip():
        raise HTTPException(status_code=400, detail="Text parameter cannot be empty")
    
    if len(text) > 1000:
        raise HTTPException(status_code=400, detail="Text too long. Maximum 1000 characters.")
    
    # Fetch response from Pollinations.ai
    pollinations_response = await fetch_pollinations_response(text, timeout)
    
    return {
        "status": "success",
        "original_prompt": text,
        "pollinations_response": pollinations_response,
        "relay_timestamp": asyncio.get_event_loop().time()
    }

@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring"""
    return {"status": "healthy", "service": "pollinations-relay"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
