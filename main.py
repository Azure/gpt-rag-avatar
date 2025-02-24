import os
import uuid
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
import httpx
from dotenv import load_dotenv
import msal

# Import the keyvault helper function (ensure keyvault.py is in your project)
from keyvault import get_secret

load_dotenv()

app = FastAPI()

# Load secrets from Key Vault
# Note: Ensure the environment variable AZURE_KEY_VAULT_NAME is set.
MSAL_CLIENT_SECRET = get_secret("avatarMsalClientSecret")
SESSION_SECRET_KEY = get_secret("avatarSessionSecretKey")
FUNCTION_KEY = get_secret("avatarOrchestratorFunctionKey")
AZURE_SPEECH_API_KEY = get_secret("avatarSpeechApiKey")

if not FUNCTION_KEY:
    raise Exception("FUNCTION_KEY not found in KeyVault.")

# Use the session secret from KeyVault for session management.
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET_KEY)

# -------------------------------
# MSAL Authentication configuration
# -------------------------------
ENABLE_AUTHENTICATION = os.getenv("ENABLE_AUTHENTICATION", "false").lower() == "true"
CLIENT_ID = os.getenv("CLIENT_ID")
AUTHORITY = os.getenv("AUTHORITY")
REDIRECT_PATH = os.getenv("REDIRECT_PATH", "/auth")
REDIRECT_URI = os.getenv("REDIRECT_URI", f"http://localhost:8000{REDIRECT_PATH}")
ADDITIONAL_SCOPES = os.getenv("ADDITIONAL_SCOPES", "")
SCOPE = ["User.Read"]
if ADDITIONAL_SCOPES:
    extra_scopes = [s.strip() for s in ADDITIONAL_SCOPES.split(",") if s.strip()]
    SCOPE.extend(extra_scopes)

# -------------------------------
# Existing configuration
# -------------------------------
ORCHESTRATOR_STREAM_URL = os.getenv("STREAMING_ENDPOINT", "http://localhost:7071/api/orcstream")

# Mount static files from the 'static' directory.
app.mount("/static", StaticFiles(directory="static"), name="static")

# -------------------------------
# MSAL helper functions
# -------------------------------
def _build_msal_app(cache=None):
    return msal.ConfidentialClientApplication(
        CLIENT_ID,
        authority=AUTHORITY,
        client_credential=MSAL_CLIENT_SECRET,
        token_cache=cache
    )

def _build_auth_url(state: str):
    msal_app = _build_msal_app()
    auth_url = msal_app.get_authorization_request_url(
        scopes=SCOPE,
        state=state,
        redirect_uri=REDIRECT_URI
    )
    return auth_url

# -------------------------------
# Authentication Endpoints
# -------------------------------
@app.get("/login")
async def login(request: Request):
    if not ENABLE_AUTHENTICATION:
        return RedirectResponse(url="/")
    state = str(uuid.uuid4())
    request.session["state"] = state
    auth_url = _build_auth_url(state)
    return RedirectResponse(url=auth_url)

@app.get(REDIRECT_PATH)
async def authorized(request: Request):
    if not ENABLE_AUTHENTICATION:
        return RedirectResponse(url="/")
    if request.query_params.get("state") != request.session.get("state"):
        return JSONResponse(content={"error": "State mismatch"}, status_code=400)
    if "error" in request.query_params:
        error_desc = request.query_params.get("error_description", "Unknown error")
        return JSONResponse(content={"error": error_desc}, status_code=400)
    code = request.query_params.get("code")
    if not code:
        return JSONResponse(content={"error": "Authorization code not found"}, status_code=400)
    msal_app = _build_msal_app()
    result = msal_app.acquire_token_by_authorization_code(
        code,
        scopes=SCOPE,
        redirect_uri=REDIRECT_URI
    )
    if "error" in result:
        return JSONResponse(content={"error": result.get("error_description", "Could not acquire token")}, status_code=400)
    request.session["user"] = result.get("id_token_claims")
    request.session["access_token"] = result.get("access_token")
    request.session["refresh_token"] = result.get("refresh_token")
    return RedirectResponse(url="/")

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    logout_url = f"{AUTHORITY}/oauth2/v2.0/logout?post_logout_redirect_uri={REDIRECT_URI}"
    return RedirectResponse(url=logout_url)

# -------------------------------
# Protected Routes (Example)
# -------------------------------
@app.get("/")
async def serve_index(request: Request):
    if ENABLE_AUTHENTICATION and not request.session.get("user"):
        return RedirectResponse(url="/login")
    return FileResponse("static/index.html")

@app.get("/favicon.ico")
async def serve_favicon(request: Request):
    if ENABLE_AUTHENTICATION and not request.session.get("user"):
        return RedirectResponse(url="/login")
    return FileResponse("static/image/favicon.ico")

# -------------------------------
# Existing Endpoints (Unchanged)
# -------------------------------
@app.post("/speak")
async def speak(request: Request):
    body = await request.json()
    question = body.get("spokenText")
    conversation_id = body.get("conversation_id", "")
    if not question:
        raise HTTPException(status_code=400, detail="Missing spokenText in request.")
    
    payload = {
        "conversation_id": conversation_id,
        "question": question,
        "text_only": True,
        "client_principal_id": body.get("client_principal_id", ""),
        "client_principal_name": body.get("client_principal_name", ""),
        "access_token": body.get("access_token", "")
    }
    
    headers = {
        "x-functions-key": FUNCTION_KEY,
        "Content-Type": "application/json"
    }
    
    async def stream_generator():
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", ORCHESTRATOR_STREAM_URL, json=payload, headers=headers) as resp:
                if resp.status_code != 200:
                    yield f"Error: {resp.status_code}"
                    return
                async for line in resp.aiter_lines():
                    if line:
                        yield line

    return StreamingResponse(stream_generator(), media_type="text/event-stream")

@app.get("/get-ice-server-token")
async def get_ice_server_token():
    speech_region = os.getenv("AZURE_SPEECH_REGION", "eastus2")
    subscription_key = AZURE_SPEECH_API_KEY
    if not subscription_key:
        raise HTTPException(status_code=400, detail="Missing Azure Speech subscription key.")

    token_url = f"https://{speech_region}.tts.speech.microsoft.com/cognitiveservices/avatar/relay/token/v1"
    async with httpx.AsyncClient() as client:
        headers = {"Ocp-Apim-Subscription-Key": subscription_key}
        response = await client.get(token_url, headers=headers)
        if response.status_code == 200:
            return JSONResponse(content=response.json())
        else:
            raise HTTPException(status_code=response.status_code, detail="Failed to get ICE server token.")

@app.get("/get-speech-region")
async def get_speech_region():
    speech_region = os.getenv("AZURE_SPEECH_REGION", "eastus2")
    return JSONResponse(content={"speech_region": speech_region})

@app.get("/get-supported-languages")
async def get_supported_languages():
    supported_languages = os.getenv("SUPPORTED_LANGUAGES", "en-US,de-DE,zh-CN,nl-NL")
    languages_list = [lang.strip() for lang in supported_languages.split(",")]
    return JSONResponse(content={"supported_languages": languages_list})

@app.get("/get-speech-token")
async def get_speech_token():
    speech_region = os.getenv("AZURE_SPEECH_REGION", "eastus2")
    subscription_key = AZURE_SPEECH_API_KEY
    if not subscription_key:
        raise HTTPException(status_code=400, detail="Missing Azure Speech subscription key.")

    token_url = f"https://{speech_region}.api.cognitive.microsoft.com/sts/v1.0/issueToken"
    async with httpx.AsyncClient() as client:
        headers = {"Ocp-Apim-Subscription-Key": subscription_key}
        response = await client.post(token_url, headers=headers)
        if response.status_code == 200:
            return JSONResponse(content={"token": response.text})
        else:
            raise HTTPException(status_code=response.status_code, detail="Failed to get speech token.")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
