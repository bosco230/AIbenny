"""``POST /chat`` — submit a text turn.

Pipeline:

1. Run :func:`openmimicry.tasks.intent.detect_task_intent` on the input.
2. If a task intent matches, submit to ``wiring.tasks`` (the
   :class:`TaskRouter`) and publish :class:`TaskSubmitted` + a forwarder
   that re-emits every :class:`TaskUpdate` as :class:`TaskUpdatedEvent`
   plus a terminal :class:`TaskCompleted`.
3. Otherwise fall back to the LLM path: ``wiring.llm.generate`` streams
   :class:`LLMChunk`; each chunk publishes :class:`LLMTokenStreamed`;
   final text publishes :class:`LLMReplyComplete`.

The endpoint returns 202 immediately — actual delivery happens on the
WS via :mod:`openmimicry_backend.projection`.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import cast
from uuid import uuid4

import yaml
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from openmimicry.core import (
    AvatarCue,
    EventBus,
    LLMAdapter,
    LLMMessage,
    LLMReplyComplete,
    LLMStarted,
    LLMTokenStreamed,
    SpeechController,
    TaskCompleted,
    TaskRequest,
    TaskRuntimeAdapter,
    TaskSubmitted,
    TaskUpdatedEvent,
)
from openmimicry.core.schemas.app import ResponsePresentationConfig
from pydantic import BaseModel

from ..llm_response import IncrementalJSONReplyExtractor, load_personality, parse_assistant_reply
from ..bible_search import find_reference
from ..bible_topics import retrieve_topic

__all__ = ["ChatRequest", "router", "run_chat_turn"]


_log = logging.getLogger(__name__)
_MIN_THINKING_SECONDS = 0.65


def _now() -> datetime:
    return datetime.now(timezone.utc)


_SHARED_RULES_PATH = Path(__file__).resolve().parents[5] / "config" / "shared_rules.yml"


def load_shared_rules(path: Path | None = None) -> str | None:
    """Rules every companion follows (e.g. Bible quoting), from shared_rules.yml.

    Read on every turn, like the personality files, so edits apply to both
    Benny and 叮當 on the next message without a restart.
    """

    try:
        data = yaml.safe_load((path or _SHARED_RULES_PATH).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(data, dict):
        return None
    parts = [str(value).strip() for value in data.values() if isinstance(value, str) and value.strip()]
    return "\n\n".join(parts) or None


class ChatRequest(BaseModel):
    text: str


router = APIRouter()


@router.post("/chat", status_code=202, response_model=None)
async def chat(req: ChatRequest, request: Request) -> dict[str, str] | JSONResponse:
    """Atomically submit a turn; never hide an input in a server-side queue."""

    submission = await request.app.state.handle_user_text(req.text, "text")
    if not submission.accepted:
        status_code = 400 if submission.reason == "empty" else 409
        return JSONResponse(
            status_code=status_code,
            content={
                "status": "rejected",
                "reason": submission.reason,
                "turn_id": submission.turn_id,
                "active_turn_id": submission.admission.active_turn_id,
            },
        )
    return {"status": "accepted", "turn_id": submission.turn_id}


async def run_chat_turn(
    text: str,
    *,
    bus: EventBus,
    llm: LLMAdapter,
    tasks: TaskRuntimeAdapter,
    speech: SpeechController | None = None,
    intent_fn: Callable[[str], TaskRequest | None] | None = None,
    history: Sequence[LLMMessage] = (),
    presentation: ResponsePresentationConfig | None = None,
    voice_enabled: bool = True,
    personality_path: str | None = None,
) -> str | None:
    """The actual chat/task pipeline. Exposed for direct use in tests.

    ``intent_fn`` defaults to lazy-importing ``openmimicry.tasks.detect_task_intent``
    so tests that drive this function directly don't have to plumb it; the
    HTTP route always passes the classifier off ``wiring.intent`` to keep
    its imports Protocol-only.
    """
    classifier = intent_fn or _lazy_intent_classifier()
    intent = classifier(text)
    if intent is not None:
        await _run_task_path(intent, bus=bus, tasks=tasks)
        return None
    return await _run_llm_path(
        text,
        bus=bus,
        llm=llm,
        speech=speech,
        history=history,
        presentation=presentation,
        voice_enabled=voice_enabled,
        personality_path=personality_path,
    )


def _lazy_intent_classifier() -> Callable[[str], TaskRequest | None]:
    """Import ``detect_task_intent`` only when the route doesn't supply one.

    Pushing the import out of module-load lets `routes.chat` stay clean
    of sibling-package imports at the top of the file.
    """
    from openmimicry.tasks import detect_task_intent

    return detect_task_intent


# ---------------------------------------------------------------------------
# Task path
# ---------------------------------------------------------------------------


async def _run_task_path(
    request_obj: object,
    *,
    bus: EventBus,
    tasks: TaskRuntimeAdapter,
) -> None:
    # `detect_task_intent` returns a fully-formed TaskRequest.
    try:
        handle = await tasks.submit(request_obj)  # type: ignore[arg-type]
    except Exception as exc:
        from openmimicry.core import ErrorEvent

        bus.publish(ErrorEvent(ts=_now(), where="backend.chat.task", message=str(exc)))
        return

    bus.publish(
        TaskSubmitted(
            ts=_now(),
            handle=handle,
            summary=getattr(request_obj, "summary", "") or "",
        )
    )

    # Stream updates back onto the bus.
    try:
        async for update in tasks.updates(handle):
            bus.publish(TaskUpdatedEvent(ts=_now(), update=update))
    except Exception as exc:
        from openmimicry.core import ErrorEvent

        bus.publish(
            ErrorEvent(
                ts=_now(),
                where="backend.chat.task_updates",
                message=str(exc),
            )
        )

    try:
        result = await tasks.result(handle)
    except Exception as exc:
        from openmimicry.core import ErrorEvent

        bus.publish(
            ErrorEvent(
                ts=_now(),
                where="backend.chat.task_result",
                message=str(exc),
            )
        )
        return

    bus.publish(TaskCompleted(ts=_now(), handle=handle, result=result))


# ---------------------------------------------------------------------------
# LLM path
# ---------------------------------------------------------------------------


async def _run_llm_path(
    text: str,
    *,
    bus: EventBus,
    llm: LLMAdapter,
    speech: SpeechController | None,
    history: Sequence[LLMMessage] = (),
    presentation: ResponsePresentationConfig | None = None,
    voice_enabled: bool = True,
    personality_path: str | None = None,
) -> str | None:
    bus.publish(LLMStarted(ts=_now()))
    thinking_started = asyncio.get_running_loop().time()

    settings = load_personality(personality_path)
    presentation = presentation or ResponsePresentationConfig()
    mode = presentation.mode
    speech_candidate = bool(
        speech is not None and voice_enabled and mode != "text_only"
    )
    utterance_id = uuid4().hex if speech_candidate else None

    shared_rules = load_shared_rules()
    messages = [
        LLMMessage(role="system", content=settings.system_prompt),
        *([LLMMessage(role="system", content=shared_rules)] if shared_rules else []),
        *history,
        LLMMessage(role="user", content=text),
    ]

    # BENNY_111T_R: optional read-only Bible reference retrieval.
    try:
        from pathlib import Path

        bible_database = (
            Path(__file__).resolve().parents[5]
            / "data" / "bible" / "bible.sqlite"
        )

        bible_verse = find_reference(bible_database, text)

        if bible_verse is None:
            bible_topic = retrieve_topic(bible_database, text)
        else:
            bible_topic = None

        if bible_topic is not None:
            topic_lines = []

            for verse in bible_topic["verses"]:
                reference = (
                    f'{verse["book_name"]} '
                    f'{verse["chapter"]}:'
                    f'{verse["verse"]}'
                )
                topic_lines.append(
                    reference + "\n" + verse["text"]
                )

            topic_context = (
                "以下係本地繁體中文和合本聖經主題參考資料。"
                "主題：" + bible_topic["topic"]
                + "\n引用經文時必須逐字保留資料庫原文，"
                "包括用字、標點及方括號，不得改寫或翻譯。"
                "請清楚標示經文出處，並區分原文與解釋。"
                "經文以外請使用自然廣東話解釋。"
                "保留原有角色個性及回覆格式。"
                + "\n\n" + "\n\n".join(topic_lines)
            )

            messages.insert(
                -1,
                LLMMessage(role="system", content=topic_context),
            )

        if bible_verse is not None:
            bible_reference = (
                f'{bible_verse["book_name"]} '
                f'{bible_verse["chapter"]}:'
                f'{bible_verse["verse"]}'
            )

            bible_context = (
                "以下係本地繁體中文和合本聖經參考資料。"
                "引用經文時，必須逐字保留資料庫原文，"
                "包括用字、標點及方括號，不得改寫或翻譯。"
                "請清楚標示經文出處，並區分原文與解釋。"
                "經文以外的解釋請使用自然廣東話。"
                "保留原有角色個性及回覆格式。"
                "\n經文出處：" + bible_reference
                + "\n經文內容：" + bible_verse["text"]
            )

            messages.insert(
                -1,
                LLMMessage(role="system", content=bible_context),
            )

    except Exception:
        # Bible retrieval must not break normal chat.
        pass

    raw_parts: list[str] = []
    speech_queue: asyncio.Queue[object] = asyncio.Queue()
    queue_end = object()
    speech_task: asyncio.Task[None] | None = None
    extractor = (
        IncrementalJSONReplyExtractor()
        if settings.structured_avatar_output
        else None
    )
    extraction_failed = False

    async def queued_text():
        while True:
            item = await speech_queue.get()
            if item is queue_end:
                return
            yield cast(str, item)

    async def start_speech(text_or_stream: object) -> None:
        assert speech is not None
        if "utterance_id" in inspect.signature(speech.say).parameters:
            await speech.say(text_or_stream, utterance_id=utterance_id)
        else:
            await speech.say(text_or_stream)

    def enqueue_speech_text(value: str) -> None:
        nonlocal speech_task
        if not value:
            return
        speech_queue.put_nowait(value)
        if speech_task is None and speech is not None:
            speech_task = asyncio.create_task(
                start_speech(queued_text()),
                name="openmimicry.chat.streaming_tts",
            )

    # BENNY_110E_26V: LLM timing
    import time as _benny_time
    _benny_llm_start = _benny_time.perf_counter()
    _benny_first_seen = False
    try:
        async for chunk in llm.generate(messages):
            if not chunk.delta:
                continue
            if not _benny_first_seen:
                _benny_first_seen = True
                print(f'[BENNY_LATENCY] llm_first_token={_benny_time.perf_counter()-_benny_llm_start:.3f}s', flush=True)
            raw_parts.append(chunk.delta)

            if not speech_candidate:
                continue

            if extractor is None:
                enqueue_speech_text(chunk.delta)
            elif not extraction_failed:
                try:
                    extracted = extractor.feed(chunk.delta)
                    enqueue_speech_text(extracted)
                except (ValueError, TypeError) as exc:
                    extraction_failed = True
                    _log.warning(
                        "Incremental reply extraction stopped; "
                        "using final parsed reply if speech has not started: %s",
                        exc,
                    )
    except Exception as exc:
        from openmimicry.core import ErrorEvent

        _log.error(
            "LLM turn failed: adapter=%s error=%s: %s",
            getattr(llm, "name", type(llm).__name__),
            type(exc).__name__,
            exc,
            exc_info=True,
        )
        bus.publish(ErrorEvent(ts=_now(), where="backend.chat.llm", message=str(exc)))
    finally:
        if extractor is not None and not extraction_failed and speech_candidate:
            try:
                enqueue_speech_text(extractor.finish())
            except (ValueError, TypeError) as exc:
                _log.warning("Could not finish incremental reply extraction: %s", exc)
        if speech_task is not None:
            speech_queue.put_nowait(queue_end)

    print(f'[BENNY_LATENCY] llm_total={_benny_time.perf_counter()-_benny_llm_start:.3f}s', flush=True)
    reply = parse_assistant_reply("".join(raw_parts), settings)
    _log.warning("BENNY_EMOTION_DEBUG emotion=%s structured=%s", reply.emotion, reply.structured)
    if not reply.structured and settings.structured_avatar_output:
        import json as _benny_json
        _benny_raw = "".join(raw_parts).strip()
        _benny_fenced = _benny_raw.startswith("```")
        _benny_think = "<think>" in _benny_raw or "</think>" in _benny_raw
        _benny_json_start = _benny_raw.startswith("{")
        _benny_json_end = _benny_raw.endswith("}")
        try:
            _benny_json.loads(_benny_raw)
            _benny_json_valid = True
        except (ValueError, TypeError):
            _benny_json_valid = False
        _log.warning(
            "BENNY_JSON_DIAG length=%s fenced=%s think=%s starts_json=%s ends_json=%s valid_json=%s",
            len(_benny_raw), _benny_fenced, _benny_think,
            _benny_json_start, _benny_json_end, _benny_json_valid,
        )

    # If structured streaming never found a usable reply, retain the original
    # full-response TTS fallback. Never replay text already sent to streaming TTS.
    if speech_candidate and reply.text and speech_task is None and speech is not None:
        speech_task = asyncio.create_task(
            start_speech(reply.text),
            name="openmimicry.chat.fallback_tts",
        )

    thinking_elapsed = asyncio.get_running_loop().time() - thinking_started
    if mode == "voice_ready" and reply.text and thinking_elapsed < _MIN_THINKING_SECONDS:
        await asyncio.sleep(_MIN_THINKING_SECONDS - thinking_elapsed)

    wants_speech = bool(speech_candidate and reply.text)

    def publish_reply() -> None:
        # Publish one display update instead of artificial chunks: this clears
        # the previous turn and prevents append-only UI artefacts. Voice-only
        # remains present in conversation history but is suppressed by the
        # bubble projector.
        if reply.text and mode != "voice_only":
            bus.publish(LLMTokenStreamed(ts=_now(), delta=reply.text))
        bus.publish(
            LLMReplyComplete(
                ts=_now(),
                full_text=reply.text,
                presentation_mode=mode,
                speech_expected=wants_speech,
                speech_utterance_id=utterance_id if wants_speech else None,
            )
        )

    if mode in {"parallel", "text_only", "voice_only"}:
        publish_reply()

    speech_ready = False
    if speech_task is not None:
        wait_ready = (
            getattr(speech, "wait_until_speech_ready", None)
            if speech is not None
            else None
        )

        if mode == "voice_ready" and wants_speech and callable(wait_ready):
            # The real SpeechController.say() only schedules playback and
            # returns quickly. Wait for scheduling, then for first audio.
            try:
                await speech_task
                readiness_timeout_s = float(
                    getattr(speech, "speech_readiness_timeout_s", 30.0)
                )
                ready_waiter = cast(Callable[..., Awaitable[object]], wait_ready)
                if "utterance_id" in inspect.signature(wait_ready).parameters:
                    speech_ready = bool(
                        await ready_waiter(
                            timeout_s=readiness_timeout_s,
                            utterance_id=utterance_id,
                        )
                    )
                else:
                    speech_ready = bool(
                        await ready_waiter(timeout_s=readiness_timeout_s)
                    )
            except Exception as exc:
                _log.warning(
                    "could not wait for speech readiness: %s",
                    exc,
                    exc_info=True,
                )
        else:
            # Publish text first, then wait for say() to finish scheduling.
            try:
                await asyncio.shield(speech_task)
            except asyncio.CancelledError:
                if not speech_task.cancelled():
                    raise
            except Exception as exc:
                _log.warning(
                    "background reply audio failed: %s",
                    exc,
                    exc_info=True,
                )

    if mode == "voice_ready":
        if wants_speech and not speech_ready:
            _log.warning(
                "voice-ready presentation fell back to text because TTS was unavailable"
            )
        publish_reply()

    # Keep the conversation lease briefly active even when a mock or
    # unusually fast LLM completes immediately. Text has already been
    # published, so this does not delay UI delivery.
    if mode != "voice_ready" and reply.text:
        elapsed = asyncio.get_running_loop().time() - thinking_started
        if elapsed < _MIN_THINKING_SECONDS:
            await asyncio.sleep(_MIN_THINKING_SECONDS - elapsed)

    bus.publish(
        AvatarCue(
            ts=_now(),
            emotion=reply.emotion,
            action=reply.action,
            intensity=reply.intensity,
            duration_ms=reply.duration_ms,
        )
    )
    return reply.text or None

