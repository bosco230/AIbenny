"""FastAPI app for the Benny & 叮當 web edition.

Run locally:  uvicorn benny_web.app:app --port 8080   (from the web/ folder)
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .auth import COOKIE, Sessions
from .brain import Brain
from .limits import LimitExceeded, Limits
from .llm import LLMError, OpenRouter
from .settings import WEB_ROOT, Settings
from .voice import AzureSpeech, VoiceError

_log = logging.getLogger("benny_web")


class LoginRequest(BaseModel):
    passcode: str = Field(max_length=200)


class ChatRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    character: str = "benny"


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=600)
    character: str = "benny"


def create_app(settings: Settings | None = None, *, brain: Brain | None = None,
               speech: AzureSpeech | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    for problem in settings.problems():
        _log.warning("CONFIG: %s", problem)
    sessions = Sessions(settings.session_secret, settings.passcode)
    limits = Limits(
        settings.data_dir / "usage.json",
        messages_per_10min=settings.messages_per_10min,
        messages_per_day=settings.messages_per_day,
        tts_chars_per_day=settings.tts_chars_per_day,
        tts_chars_per_day_total=settings.tts_chars_per_day_total,
        stt_per_day=settings.stt_requests_per_day,
    )
    llm = OpenRouter(settings.openrouter_key, settings.openrouter_url)
    brain = brain or Brain(settings, llm)
    speech = speech or AzureSpeech(settings.azure_key, settings.azure_region)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):  # type: ignore[no-untyped-def]
        yield
        await brain.close()
        await speech.close()
        await llm.close()

    app = FastAPI(title="Benny & 叮當", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    def visitor(request: Request) -> str:
        visitor_id = sessions.visitor(request.cookies.get(COOKIE))
        if visitor_id is None:
            raise HTTPException(status_code=401, detail="請先輸入通行碼")
        return visitor_id

    def character(name: str) -> str:
        if name not in settings.characters:
            raise HTTPException(status_code=404, detail="unknown character")
        return name

    @app.exception_handler(LimitExceeded)
    async def _limit(_request: Request, exc: LimitExceeded) -> JSONResponse:
        return JSONResponse({"detail": exc.message}, status_code=429)

    @app.post("/api/login")
    async def login(body: LoginRequest, request: Request, response: Response) -> dict[str, Any]:
        client = request.client.host if request.client else "unknown"
        if sessions.too_many_attempts(client):
            raise HTTPException(status_code=429, detail="試得太多次，請一分鐘後再試。")
        if not sessions.check_passcode(body.passcode.strip(), client):
            raise HTTPException(status_code=401, detail="通行碼唔啱")
        existing = sessions.visitor(request.cookies.get(COOKIE))
        _, cookie = sessions.issue(existing)
        response.set_cookie(COOKIE, cookie, max_age=30 * 86400, httponly=True,
                            samesite="lax", secure=settings.secure_cookies)
        return {"ok": True}

    @app.post("/api/logout")
    async def logout(response: Response) -> dict[str, Any]:
        response.delete_cookie(COOKIE)
        return {"ok": True}

    @app.get("/api/me")
    async def me(visitor_id: str = Depends(visitor)) -> dict[str, Any]:
        return {
            "ok": True,
            "voice": speech.available,
            "characters": [{"id": c.id, "name": c.name} for c in settings.characters.values()],
        }

    @app.post("/api/chat")
    async def chat(body: ChatRequest, visitor_id: str = Depends(visitor)) -> dict[str, Any]:
        limits.message(visitor_id)
        try:
            return await brain.reply(visitor_id, character(body.character), body.text.strip())
        except LLMError as exc:
            _log.warning("LLM failed: %s", exc)
            raise HTTPException(status_code=502, detail="對話服務暫時有問題，請遲啲再試。") from exc

    @app.post("/api/speak")
    async def speak(body: SpeakRequest, visitor_id: str = Depends(visitor)) -> dict[str, Any]:
        if not speech.available:
            raise HTTPException(status_code=503, detail="語音未設定")
        limits.tts(visitor_id, len(body.text))
        voice = settings.characters[character(body.character)].azure_voice
        try:
            return await speech.synthesize(body.text, voice)
        except VoiceError as exc:
            raise HTTPException(status_code=502, detail="語音服務暫時有問題") from exc

    @app.post("/api/listen")
    async def listen(request: Request, visitor_id: str = Depends(visitor)) -> dict[str, Any]:
        if not speech.available:
            raise HTTPException(status_code=503, detail="語音未設定")
        limits.stt(visitor_id)
        audio = await request.body()
        try:
            return {"text": await speech.transcribe(audio)}
        except VoiceError as exc:
            raise HTTPException(status_code=400, detail="聽唔清楚，可唔可以再講一次？") from exc

    @app.post("/api/forget")
    async def forget(visitor_id: str = Depends(visitor)) -> dict[str, Any]:
        await brain.forget(visitor_id)
        return {"ok": True}

    @app.get("/healthz")
    async def health() -> dict[str, Any]:
        return {"ok": not settings.problems()}

    # Only the two avatar folders are public, not the whole characters/ dir.
    for route, folder in (
        ("/avatar/benny", settings.characters_dir / "ai_girlfriend"),
        ("/avatar/dingdong", settings.characters_dir / "dingdong" / "faces"),
    ):
        if folder.is_dir():
            app.mount(route, StaticFiles(directory=folder), name=route.strip("/").replace("/", "-"))
    app.mount("/static", StaticFiles(directory=WEB_ROOT / "static"), name="static")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(WEB_ROOT / "static" / "index.html", headers={"Cache-Control": "no-cache"})

    return app


app = create_app()
