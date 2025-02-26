import asyncio
import json
import logging
import os
import secrets
import uuid

import aiofiles
import httpx
import msal
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import (FileResponse, JSONResponse, RedirectResponse,
                               StreamingResponse)
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from keyvault import get_secret

load_dotenv()

app = FastAPI()

# Logging configuration
logging.getLogger('azure').setLevel(logging.WARNING)
logging.basicConfig(level=os.environ.get('LOGLEVEL', 'DEBUG').upper(), force=True)
logging.getLogger("uvicorn.error").propagate = True
logging.getLogger("uvicorn.access").propagate = True

# -------------------------------
# File-based Session Middleware using request.state
# -------------------------------
class FileSessionMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, session_dir: str = "sessions", cookie_name: str = "session_id", max_age: int = 86400):
        super().__init__(app)
        self.session_dir = session_dir
        self.cookie_name = cookie_name
        self.max_age = max_age
        os.makedirs(session_dir, exist_ok=True)

    async def dispatch(self, request: Request, call_next):
        session_id = request.cookies.get(self.cookie_name)
        if session_id:
            session_file = os.path.join(self.session_dir, f"{session_id}.json")
            if os.path.exists(session_file):
                async with aiofiles.open(session_file, mode="r") as f:
                    content = await f.read()
                    try:
                        session_data = json.loads(content)
                    except Exception as e:
                        logging.error(f"Error decoding session file: {e}")
                        session_data = {}
            else:
                session_data = {}
        else:
            session_data = {}

        # Instead of assigning to request.session, we assign to request.state.session.
        request.state.session = session_data

        response = await call_next(request)

        # If no session_id exists, create one and set it as a cookie.
        if not session_id:
            session_id = secrets.token_hex(16)
            response.set_cookie(
                key=self.cookie_name,
                value=session_id,
                max_age=self.max_age,
                httponly=True,
                samesite="lax"
            )

        session_file = os.path.join(self.session_dir, f"{session_id}.json")
        async with aiofiles.open(session_file, mode="w") as f:
            await f.write(json.dumps(request.state.session))
        return response

app.add_middleware(FileSessionMiddleware)

# -------------------------------
# Authentication Configuration
# -------------------------------
ENABLE_AUTHENTICATION = os.getenv("ENABLE_AUTHENTICATION", "false").lower() == "true"
CLIENT_ID = os.getenv("CLIENT_ID", "your_client_id")
AUTHORITY = os.getenv("AUTHORITY", "https://login.microsoftonline.com/your_tenant_id")
REDIRECT_PATH = os.getenv("REDIRECT_PATH", "/getAToken")
REDIRECT_URI = os.getenv("REDIRECT_URI", f"http://localhost:8000{REDIRECT_PATH}")
BASIC_SCOPE = ["User.Read"]
OTHER_AUTH_SCOPES = os.getenv("OTHER_AUTH_SCOPES", "")

# -------------------------------
# Authentication Secrets
# -------------------------------
MSAL_CLIENT_SECRET = get_secret(os.getenv("APP_SERVICE_CLIENT_SECRET_NAME", "appServiceClientSecretKey"))
SESSION_SECRET_KEY = get_secret("avatarSessionSecretKey")
FUNCTION_KEY = get_secret("avatarOrchestratorFunctionKey")
AZURE_SPEECH_API_KEY = get_secret("avatarSpeechApiKey")

if not FUNCTION_KEY:
    raise Exception("FUNCTION_KEY not found in KeyVault.")

app.mount("/static", StaticFiles(directory="static"), name="static")

# -------------------------------
# MSAL Helper Functions (using request.state.session)
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
    return msal_app.get_authorization_request_url(
        scopes=BASIC_SCOPE,
        state=state,
        redirect_uri=REDIRECT_URI
    )

def _load_cache(request: Request):
    cache = msal.SerializableTokenCache()
    if "msal_cache" in request.state.session:
        try:
            cache.deserialize(request.state.session["msal_cache"])
        except Exception as e:
            logging.error(f"Error deserializing cache: {e}")
    return cache

def _save_cache(request: Request, cache):
    if cache.has_state_changed:
        request.state.session["msal_cache"] = cache.serialize()

async def get_valid_access_token(request: Request, scopes: list):
    cache = _load_cache(request)
    msal_app = _build_msal_app(cache=cache)
    accounts = msal_app.get_accounts()
    account = accounts[0] if accounts else None
    result = msal_app.acquire_token_silent(scopes, account=account)
    if not result or "access_token" not in result:
        raise Exception("Could not refresh token silently: no token found in cache.")
    if "error" in result:
        raise Exception(result.get("error_description", "Could not refresh token silently."))
    _save_cache(request, cache)
    return result.get("access_token")

# -------------------------------
# Authentication Endpoints
# -------------------------------
@app.get("/login")
async def login(request: Request):
    if not ENABLE_AUTHENTICATION:
        return RedirectResponse(url="/", status_code=303)
    state = str(uuid.uuid4())
    request.state.session["state"] = state
    auth_url = _build_auth_url(state)
    return RedirectResponse(url=auth_url, status_code=303)

@app.get(REDIRECT_PATH)
async def authorized(request: Request):
    if not ENABLE_AUTHENTICATION:
        return RedirectResponse(url="/", status_code=303)
    if request.state.session.get("user"):
        return RedirectResponse(url="/", status_code=303)
    if request.query_params.get("state") != request.state.session.get("state"):
        return JSONResponse(content={"error": "State mismatch"}, status_code=400)
    if "error" in request.query_params:
        error_desc = request.query_params.get("error_description", "Unknown error")
        return JSONResponse(content={"error": error_desc}, status_code=400)
    code = request.query_params.get("code")
    if not code:
        return JSONResponse(content={"error": "Authorization code not found"}, status_code=400)
    cache = _load_cache(request)
    msal_app = _build_msal_app(cache=cache)
    result = msal_app.acquire_token_by_authorization_code(
        code,
        scopes=BASIC_SCOPE,
        redirect_uri=REDIRECT_URI
    )
    if "error" in result:
        return JSONResponse(
            content={"error": result.get("error_description", "Could not acquire token")},
            status_code=400
        )
    user_claims = result.get("id_token_claims", {})
    minimal_user = {
        "oid": user_claims.get("oid"),
        "preferred_username": user_claims.get("preferred_username") or user_claims.get("upn")
    }
    request.state.session["user"] = minimal_user
    request.state.session["graph_access_token"] = result.get("access_token")
    request.state.session["refresh_token"] = result.get("refresh_token")
    _save_cache(request, cache)
    request.state.session.pop("state", None)
    return RedirectResponse(url="/", status_code=303)

@app.get("/logout")
async def logout(request: Request):
    request.state.session.clear()
    logout_url = f"{AUTHORITY}/oauth2/v2.0/logout?post_logout_redirect_uri={REDIRECT_URI}"
    return RedirectResponse(url=logout_url, status_code=303)

# -------------------------------
# Authorization Check (Extra Token Handling)
# -------------------------------
async def check_authorization(request: Request):
    if not ENABLE_AUTHENTICATION:
        return {
            "authorized": True,
            "client_principal_id": "no-auth",
            "client_principal_name": "anonymous",
            "client_group_names": [],
            "access_token": None
        }
    user = request.state.session.get("user")
    if not user:
        logging.info("No user in session; user not authenticated.")
        return {
            "authorized": False,
            "client_principal_id": None,
            "client_principal_name": None,
            "client_group_names": [],
            "access_token": None
        }
    client_principal_id = user.get("oid")
    client_principal_name = user.get("preferred_username") or user.get("upn")
    try:
        graph_access_token = await get_valid_access_token(request, BASIC_SCOPE)
        request.state.session["graph_access_token"] = graph_access_token
    except Exception as ex:
        logging.error(f"Failed to refresh Graph token: {str(ex)}")
        graph_access_token = request.state.session.get("graph_access_token", None)
    other_access_token = None
    if OTHER_AUTH_SCOPES:
        try:
            scopes = [s.strip() for s in OTHER_AUTH_SCOPES.split(",") if s.strip()]
            other_access_token = await get_valid_access_token(request, scopes)
            request.state.session["other_access_token"] = other_access_token
        except Exception as ex:
            logging.error(f"Failed to refresh token for other scopes: {str(ex)}")
            other_access_token = request.state.session.get("other_access_token", None)
    access_token = other_access_token if other_access_token else graph_access_token
    groups = []
    if graph_access_token:
        try:
            graph_headers = {"Authorization": f"Bearer {graph_access_token}"}
            graph_url = "https://graph.microsoft.com/v1.0/me/memberOf"
            async with httpx.AsyncClient() as client:
                response = await client.get(graph_url, headers=graph_headers)
                response.raise_for_status()
                group_data = response.json()
                groups = [g.get("displayName", "missing-group") for g in group_data.get("value", [])]
        except Exception as e:
            logging.info(f"Failed to get user groups from Graph API: {e}")
    return {
        "authorized": True,
        "client_principal_id": client_principal_id,
        "client_principal_name": client_principal_name,
        "client_group_names": groups,
        "access_token": access_token
    }

# -------------------------------
# Protected Routes and Endpoints (using request.state.session)
# -------------------------------
@app.get("/")
async def serve_index(request: Request):
    if ENABLE_AUTHENTICATION and not request.state.session.get("user"):
        return RedirectResponse(url="/login", status_code=303)
    return FileResponse("static/index.html")

@app.get("/favicon.ico")
async def serve_favicon(request: Request):
    if ENABLE_AUTHENTICATION and not request.state.session.get("user"):
        return RedirectResponse(url="/login", status_code=303)
    return FileResponse("static/image/favicon.ico")

@app.post("/speak")
async def speak(request: Request):
    body = await request.json()
    question = body.get("spokenText")
    conversation_id = body.get("conversation_id", "")
    if not question:
        raise HTTPException(status_code=400, detail="Missing spokenText in request.")
    auth_info = await check_authorization(request)
    if not auth_info.get("authorized"):
        return JSONResponse(
            content={
                "answer": "You are not authorized to access this service. Please contact your administrator.",
                "thoughts": "User not authorized.",
                "conversation_id": conversation_id
            },
            status_code=401
        )
    access_token = auth_info.get("access_token")
    payload = {
        "conversation_id": conversation_id,
        "question": question,
        "text_only": True,
        "client_principal_id": auth_info.get("client_principal_id"),
        "client_principal_name": auth_info.get("client_principal_name"),
        "client_group_names": auth_info.get("client_group_names")
    }
    if access_token:
        payload["access_token"] = access_token
    headers = {
        "x-functions-key": FUNCTION_KEY,
        "Content-Type": "application/json"
    }
    async def stream_generator():
        logging.info("Sending request to streaming endpoint with payload: %s", payload)
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST",
                os.getenv("STREAMING_ENDPOINT", "http://localhost:7071/api/orcstream"),
                json=payload,
                headers=headers
            ) as resp:
                logging.info("Received response with status code: %s", resp.status_code)
                if resp.status_code != 200:
                    yield f"Error: {resp.status_code}"
                    return
                last_yield = asyncio.get_event_loop().time()
                hearbeatcount = 0
                async for line in resp.aiter_lines():
                    now = asyncio.get_event_loop().time()
                    if now - last_yield > 15:
                        # Yield heartbeat to keep connection alive
                        hearbeatcount += 1
                        logging.info("Yelding heartbeat ", hearbeatcount)
                        yield ":\n\n"  # SSE comment heartbeat
                        last_yield = now
                    if line:
                        logging.info("Received line from stream: %s", line)
                        yield line
                        last_yield = now

    return StreamingResponse(stream_generator(), media_type="text/event-stream")

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

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
