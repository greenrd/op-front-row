from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import instagram, llm
from .demo_data import demo_threads
from .models import SummariseRequest, SummaryResponse, Thread
from .settings import SettingsUpdate, apply_update, load_settings, save_settings

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="Front Row – Instagram DM idea summariser")

_thread_cache: list[Thread] = []


@app.get("/api/settings")
def get_settings() -> dict[str, Any]:
    return load_settings().public()


@app.put("/api/settings")
def update_settings(update: SettingsUpdate) -> dict[str, Any]:
    settings = apply_update(load_settings(), update)
    save_settings(settings)
    return settings.public()


@app.get("/api/status")
def status() -> dict[str, Any]:
    s = load_settings()
    return {
        "llm_configured": s.llm_configured(),
        "instagram_configured": s.instagram_configured(),
        "demo_mode": s.demo_mode,
        "ig_username": s.ig_username,
    }


@app.get("/api/instagram/login")
def instagram_login() -> RedirectResponse:
    s = load_settings()
    if not (s.ig_app_id and s.ig_app_secret and s.public_base_url):
        raise HTTPException(400, "Set the Instagram App ID, App Secret and Public base URL in Settings first.")
    return RedirectResponse(instagram.authorize_url(s))


@app.get("/api/instagram/callback")
async def instagram_callback(code: str | None = None, error: str | None = None, error_description: str | None = None):
    if error or not code:
        return RedirectResponse(f"/#/settings?error={error_description or error or 'Instagram login cancelled'}")
    s = load_settings()
    try:
        token = await instagram.exchange_code(s, code.split("#")[0])
        profile = await instagram.fetch_profile(token)
    except instagram.InstagramError as e:
        return RedirectResponse(f"/#/settings?error={e}")
    s.ig_access_token = token
    s.ig_username = profile.get("username", "")
    s.ig_user_id = str(profile.get("user_id") or profile.get("id") or "")
    s.demo_mode = False
    save_settings(s)
    return RedirectResponse("/#/")


@app.post("/api/instagram/disconnect")
def instagram_disconnect() -> dict[str, Any]:
    s = load_settings()
    s.ig_access_token = ""
    s.ig_username = ""
    s.ig_user_id = ""
    save_settings(s)
    _thread_cache.clear()
    return s.public()


@app.post("/api/instagram/verify")
async def instagram_verify() -> dict[str, Any]:
    s = load_settings()
    if not s.ig_access_token:
        raise HTTPException(400, "No access token configured.")
    try:
        profile = await instagram.fetch_profile(s.ig_access_token)
    except instagram.InstagramError as e:
        raise HTTPException(502, str(e))
    s.ig_username = profile.get("username", "")
    s.ig_user_id = str(profile.get("user_id") or profile.get("id") or "")
    save_settings(s)
    return s.public()


@app.get("/api/threads")
async def get_threads(days: int = 7) -> dict[str, Any]:
    global _thread_cache
    s = load_settings()
    if s.demo_mode:
        threads = demo_threads()
        source = "demo"
    elif s.instagram_configured():
        try:
            threads = await instagram.fetch_threads(s.ig_access_token, days=days)
        except instagram.InstagramError as e:
            raise HTTPException(502, str(e))
        source = "instagram"
    else:
        raise HTTPException(400, "Instagram is not connected. Connect it in Settings or enable demo mode.")
    _thread_cache = threads
    return {
        "source": source,
        "days": days,
        "threads": [t.model_dump(mode="json") for t in threads],
    }


@app.post("/api/summarise")
async def summarise(req: SummariseRequest) -> SummaryResponse:
    s = load_settings()
    if not s.llm_configured():
        raise HTTPException(428, "LLM endpoint and API key are not configured. Go to Settings.")
    wanted = set(req.message_ids)
    messages = [m for t in _thread_cache for m in t.messages if m.id in wanted]
    if not messages:
        raise HTTPException(400, "No messages selected (or thread cache empty – reload threads first).")
    try:
        return await llm.summarise(s, messages)
    except llm.LLMError as e:
        raise HTTPException(502, str(e))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
