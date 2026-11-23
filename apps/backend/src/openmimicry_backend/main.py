"""``main.py`` — the FastAPI app, lifespan, routes, and WS mount.

This file is intentionally thin. The interesting work happens in
:mod:`openmimicry_backend.wiring`. ``main`` only assembles the FastAPI
surface from the :class:`Wiring` produced there.

Run with::

    uvicorn openmimicry_backend.main:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
from openmimicry.core import (
    AppConfig,
    LLMMessage,
    TaskHandle,
    UserSpeechFinal,
    UserTextSubmitted,
)
from openmimicry.core.config import load as load_config

from .appearance import load_appearance
from .character_import import CharacterRegistry
from .character_memory import CharacterMemoryManager
from .character_switch import CharacterSwitchController
from .characters import DEFAULT_CHARACTER_ID, get_character
from .conversation import ConversationCoordinator, TurnSubmission
from .diagnostics import install_diagnostics
from .routes import (
    admin_router,
    appearance_router,
    characters_router,
    chat_router,
    companions_router,
    dashboard_router,
    diagnostics_router,
    health_router,
    interaction_router,
    llm_router,
    memory_router,
    novels_router,
    mode_router,
    pack_router,
    personality_router,
    voice_clone_router,
    voice_profiles_router,
)
from .routes.characters import character_message
from .routes.chat import run_chat_turn
from .supervisor import RuntimeSupervisor, TurnAdmission, TurnSource
from .voice_profiles import VoiceProfileStore
from .wiring import Wiring, build_runtime
from .ws import BroadcastBridge, ws_endpoint

__all__ = ["app", "create_app", "run_uvicorn"]


_log = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _module_available(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _load_app_config() -> tuple[AppConfig, str | None]:
    """Load :class:`AppConfig` from ``OPENMIMICRY_CONFIG_PATH`` or defaults."""
    path_env = os.environ.get("OPENMIMICRY_CONFIG_PATH")
    # v1 files are upgraded in memory only. The loader never overwrites the
    # user's source file, so rollback remains a matter of selecting the old
    # executable/config again.
    return load_config(path_env, allow_migrate=True), path_env


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Build the runtime, start the orchestrator + speech, tear it all down."""
    config, config_path = _load_app_config()
    appearance = load_appearance()
    presentation = config.interaction.response_presentation
    appearance = appearance.model_copy(
        update={
            "behaviour": appearance.behaviour.model_copy(
                update={
                    "bubble": appearance.behaviour.bubble.model_copy(
                        update={
                            "base_ms": presentation.base_ms,
                            "ms_per_character": presentation.ms_per_character,
                            "min_ms": presentation.minimum_ms,
                            "max_ms": presentation.maximum_ms,
                        }
                    )
                }
            )
        }
    )
    user_character_root = str(Path(config.app.data_dir).expanduser() / "characters")
    character_roots = [
        user_character_root,
        *(
            root
            for root in config.avatar.pack_roots
            if Path(root).expanduser().resolve() != Path(user_character_root).resolve()
        ),
    ]
    character_registry = CharacterRegistry(
        character_roots,
        reject_licenses=(
            config.distribution.reject_licenses
            if config.distribution.profile == "commercial"
            else None
        ),
    )

    # The dashboard persists the selected pack in the per-user overlay. Resolve
    # its concrete private/bundled path before the orchestrator starts; a stale
    # selection falls back to the bundled default without making the backend
    # unavailable.
    selected_pack = config.avatar.pack
    try:
        selected_pack_path = character_registry.resolve(selected_pack)
    except ValueError as exc:
        fallback_pack = "octomimic"
        _log.warning(
            "saved avatar pack %r is unavailable (%s); using %s",
            selected_pack,
            exc,
            fallback_pack,
        )
        selected_pack = fallback_pack
        selected_pack_path = character_registry.resolve(selected_pack)
    runtime_settings = {name: dict(values) for name, values in config.avatar.runtimes.items()}
    runtime_settings[config.avatar.runtime] = {
        **runtime_settings.get(config.avatar.runtime, {}),
        "pack_path": str(selected_pack_path),
    }
    config = config.model_copy(
        update={
            "avatar": config.avatar.model_copy(
                update={"pack": selected_pack, "runtimes": runtime_settings}
            )
        }
    )

    # BENNY_110E_29G: Preload LiteLLM before the first conversation.
    if config.llm.active_backend == 'ollama':
        preload_started = time.perf_counter()
        import litellm  # noqa: F401
        _log.info(
            'BENNY_LATENCY litellm_preload=%.3fs',
            time.perf_counter() - preload_started,
        )
    # BENNY_110E_29Z: Preload Ollama model before accepting conversations.
    if config.llm.active_backend == "ollama":
        try:
            import asyncio as _benny_asyncio
            import json as _benny_json
            import urllib.request as _benny_urlrequest

            _benny_backend = config.llm.backends["ollama"]
            _benny_model = _benny_backend.model
            for _benny_prefix in ("ollama_chat/", "ollama/"):
                if _benny_model.startswith(_benny_prefix):
                    _benny_model = _benny_model[len(_benny_prefix):]
                    break

            _benny_base = (
                _benny_backend.api_base or "http://127.0.0.1:11434"
            ).rstrip("/")
            _benny_url = _benny_base + "/api/generate"

            def _benny_warmup():
                payload = _benny_json.dumps(
                    {"model": _benny_model}
                ).encode("utf-8")
                request = _benny_urlrequest.Request(
                    _benny_url,
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with _benny_urlrequest.urlopen(
                    request, timeout=30
                ) as response:
                    result = _benny_json.load(response)
                return result.get("done_reason")

            _benny_warmup_started = time.perf_counter()
            _benny_result = await _benny_asyncio.to_thread(
                _benny_warmup
            )
            _log.warning(
                "BENNY_WARMUP model=%s result=%s elapsed=%.3fs",
                _benny_model,
                _benny_result,
                time.perf_counter() - _benny_warmup_started,
            )
        except Exception as _benny_exc:
            _log.warning(
                "BENNY_WARMUP skipped: %s", _benny_exc
            )


    # BENNY_110E_31O: HTTP timing diagnostics only.
    if config.llm.active_backend == "ollama":
        from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler
        import time as _benny_http_time

        _benny_original_post = AsyncHTTPHandler.post

        async def _benny_timed_post(self, *args, **kwargs):
            _url = kwargs.get("url")
            if _url is None and args:
                _url = args[0]

            _is_ollama = (
                "127.0.0.1:11434" in str(_url)
                and "/api/chat" in str(_url)
            )

            _started = _benny_http_time.perf_counter()

            if _is_ollama:
                print(
                    "[BENNY_HTTP] post_start="
                    f"{_started:.6f}",
                    flush=True,
                )

            try:
                return await _benny_original_post(
                    self, *args, **kwargs
                )
            finally:
                if _is_ollama:
                    _ended = _benny_http_time.perf_counter()
                    print(
                        "[BENNY_HTTP] post_elapsed="
                        f"{_ended - _started:.3f}s",
                        flush=True,
                    )

        AsyncHTTPHandler.post = _benny_timed_post

    # BENNY_110E_32C completion timing
    if config.llm.active_backend == "ollama":
        import litellm.main as _benny_main
        import time as _benny_clock

        _benny_original_completion = _benny_main.completion

        def _benny_timed_completion(*args, **kwargs):
            _benny_started = _benny_clock.perf_counter()
            print(
                f"[BENNY_COMPLETION] start={_benny_started:.6f}",
                flush=True,
            )
            return _benny_original_completion(*args, **kwargs)

        _benny_main.completion = _benny_timed_completion

    bridge = BroadcastBridge()
    wiring: Wiring = await build_runtime(config, ws_bridge=bridge, config_path=config_path)
    supervisor = RuntimeSupervisor(bus=wiring.bus)
    diagnostics = install_diagnostics(config.app.data_dir)

    mode_state = {
        "continuous_listening": config.voice.modes.continuous_listening,
        "live_wake": config.voice.modes.live_wake,
        "agent_voice": config.voice.modes.agent_voice,
        "wake_names": list(wiring.speech.wake_names),
        "wake_aliases": list(getattr(wiring.speech, "wake_aliases", [])),
        "stt_model": getattr(wiring.speech, "stt_model", config.voice.stt.model),
        "post_speech_silence_duration": wiring.speech.post_speech_silence_duration,
    }
    presentation_state = {"value": config.interaction.response_presentation}
    proactive_idle = {"last_user_activity": time.monotonic(), "topic_index": 0}
    # Finance-novel library: data/novels/inbox -> data/novels/novels.sqlite.
    from openmimicry.memory.semantic import OllamaEmbedder

    from .novels import NovelLibrary

    _repo_root = Path(__file__).resolve().parents[4]
    novels = NovelLibrary(
        _repo_root / "data" / "novels" / "novels.sqlite",
        _repo_root / "data" / "novels" / "inbox",
        OllamaEmbedder(
            model=config.memory.embedding_model or "bge-m3",
            base_url=config.memory.embedding_endpoint,
            cpu_only=config.memory.embedding_device == "cpu",
        ),
    )
    app.state.novels = novels

    # Phase 2: finished turns waiting to be condensed into a stored summary.
    summary_state: dict = {"pending": [], "task": None}

    def _schedule_summary(*, force: bool = False) -> None:
        pending: list[tuple[str, str]] = summary_state["pending"]
        if not pending or not wiring.memory.supports_summaries:
            return
        if not force and len(pending) < config.memory.summary_batch_turns:
            return
        running = summary_state["task"]
        if running is not None and not running.done():
            return
        batch = list(pending)
        pending.clear()

        async def _summarize() -> None:
            try:
                summary = await wiring.memory.summarize(batch)
                _log.info("MEMORY_SUMMARY_STORED turns=%d stored=%s", len(batch), bool(summary))
            except Exception:
                _log.exception("MEMORY_SUMMARY_FAILED turns=%d", len(batch))

        summary_state["task"] = asyncio.create_task(
            _summarize(), name="openmimicry.memory.summarize"
        )

    async def _run_ordered_turn(text: str, history, *, remember_turn: bool = True) -> str | None:
        # BENNY_110E_26O: latency diagnostic
        _benny_t0 = time.monotonic()
        memory_context = await wiring.memory.context(text)
        _benny_t1 = time.monotonic()
        print(f"[BENNY_LATENCY] memory_context={_benny_t1-_benny_t0:.3f}s", flush=True)
        augmented_history = list(history)
        if memory_context:
            augmented_history.append(LLMMessage(role="system", content=memory_context))
        # Finance-novel library, shared by Benny and 叮當.
        novel_context = None
        if remember_turn:  # proactive prompts are not user questions
            try:
                async with asyncio.timeout(2.0):
                    novel_context = await novels.context(text)
            except Exception:
                _log.warning("NOVEL_CONTEXT_FAILED", exc_info=True)
        if novel_context:
            augmented_history.append(LLMMessage(role="system", content=novel_context))
        reply = await run_chat_turn(
            text,
            bus=wiring.bus,
            llm=wiring.llm,
            tasks=wiring.tasks,
            speech=wiring.speech if mode_state["agent_voice"] else None,
            intent_fn=wiring.intent,
            history=augmented_history,
            presentation=presentation_state["value"],
            voice_enabled=bool(mode_state["agent_voice"]),
            personality_path=(
                str(get_character(character_memories.active_id).personality_path)
                if character_memories.active_id != DEFAULT_CHARACTER_ID
                else None
            ),
        )
        if reply and config.memory.enabled and remember_turn:
            wiring.memory.observe(
                text,
                reply,
                source=f"conversation:{diagnostics.session_id}",
            )
            summary_state["pending"].append((text, reply))
            _schedule_summary()
        return reply

    conversation = ConversationCoordinator(
        run_turn=_run_ordered_turn,
        supervisor=supervisor,
        history_turns=config.llm.history_turns,
    )

    # BENNY_116C_7: separate short-term history per character.
    # Benny remains the default; switching is not enabled yet.
    character_memories = CharacterMemoryManager(
        max_turns=config.llm.history_turns,
    )
    conversation.memory = character_memories.active_memory()

    # BENNY_116C_15: register a guarded character switch controller.
    # No user-facing switch command is enabled yet.
    async def _character_speech_idle() -> bool:
        return bool(wiring.speech.is_idle)

    character_switch = CharacterSwitchController(
        coordinator=conversation,
        memories=character_memories,
        supervisor=supervisor,
        is_idle=_character_speech_idle,
        is_speech_idle=lambda: bool(wiring.speech.is_idle),
    )

    async def _handle_user_text(
        text: str,
        source: TurnSource = "text",
    ) -> TurnSubmission:
        if source != "proactive" and text.strip():
            proactive_idle["last_user_activity"] = time.monotonic()
        async def _accepted(_admission: TurnAdmission) -> None:
            # A freshly admitted turn owns presentation.  Stop speech from the
            # previous completed turn before publishing user history.  Its late
            # TTS terminal event cannot clear this turn's authoritative
            # ``thinking`` state (the avatar director enforces that invariant).
            await wiring.speech.interrupt()
            if source == "text":
                wiring.bus.publish(UserTextSubmitted(ts=_utc_now(), text=text.strip()))

        return await conversation.submit_background(
            text,
            source=source,
            on_accepted=_accepted,
        )

    async def _apply_mode_toggle(key: str, value: bool) -> None:
        if key == "continuous_listening":
            if value:
                await wiring.speech.enable_continuous_listening()
                mode_state["live_wake"] = False
            else:
                await wiring.speech.disable_live_listening()
        elif key == "live_wake":
            if value:
                await wiring.speech.enable_live_listening(wake_names=None)
                mode_state["continuous_listening"] = False
            else:
                await wiring.speech.disable_live_listening()
        elif key == "agent_voice" and not value:
            await wiring.speech.interrupt()
        elif key not in mode_state:
            raise ValueError(f"unknown mode key: {key!r}")
        mode_state[key] = value

    def _mode_status() -> dict[str, object]:
        stt_name = getattr(wiring.stt, "name", "unknown")
        tts_name = getattr(wiring.tts, "name", "unknown")
        real_input = not stt_name.startswith("mock")
        real_output = not tts_name.startswith("mock")
        if stt_name == "realtimestt":
            real_input = _module_available("RealtimeSTT")
        elif stt_name == "isolated-faster-whisper":
            real_input = all(
                _module_available(module) for module in ("faster_whisper", "sounddevice", "numpy")
            )
            real_input = real_input and bool(getattr(wiring.speech, "stt_ready", False))
        if tts_name == "realtimetts":
            real_output = _module_available("RealtimeTTS")
        elif tts_name == "isolated-piper":
            tts_model = (
                Path(config.voice.tts.data_dir).expanduser() / f"{config.voice.tts.voice}.onnx"
            )
            real_output = (
                _module_available("piper")
                and tts_model.is_file()
                and Path(f"{tts_model}.json").is_file()
            )
            real_output = real_output and bool(getattr(wiring.speech, "tts_ready", False))
        elif tts_name == "elevenlabs":
            real_output = bool(getattr(wiring.tts, "has_credentials", False))
        return {
            **mode_state,
            "listening_mode": getattr(wiring.speech, "listening_mode", "off"),
            "ptt_active": getattr(wiring.speech, "ptt_active", False),
            "wake_names": list(getattr(wiring.speech, "wake_names", ["Mimi"])),
            "wake_aliases": list(getattr(wiring.speech, "wake_aliases", [])),
            "stt_model": str(getattr(wiring.speech, "stt_model", "medium.en")),
            "stt_runtime": dict(getattr(wiring.stt, "runtime_info", {})),
            "post_speech_silence_duration": float(
                getattr(wiring.speech, "post_speech_silence_duration", 1.0)
            ),
            "stt_adapter": stt_name,
            "tts_adapter": tts_name,
            "real_input": real_input,
            "real_output": real_output,
            "llm_backend": getattr(wiring.llm, "active_backend", None),
            "llm_model": getattr(
                wiring.llm,
                "active_model",
                getattr(getattr(wiring.llm, "_settings", None), "model", "unknown"),
            ),
            "history_turns": conversation.memory.max_turns,
            "diagnostics_session": diagnostics.session_id,
            "diagnostics_log": str(diagnostics.log_path),
            "input_install_hint": (
                None
                if real_input or stt_name.startswith("mock")
                else r"Run .\scripts\win\install.bat openrouter-voice"
            ),
            "output_install_hint": (
                None
                if real_output or tts_name.startswith("mock")
                else r"Run .\scripts\win\install.bat openrouter-voice"
            ),
        }

    async def _cancel_task(raw_handle: dict[str, object]) -> None:
        await wiring.tasks.cancel(TaskHandle.model_validate(raw_handle))

    app.state.wiring = wiring
    app.state.config = config
    app.state.presentation_state = presentation_state
    app.state.bridge = bridge
    app.state.handle_user_text = _handle_user_text
    app.state.apply_mode_toggle = _apply_mode_toggle
    app.state.mode_state = mode_state
    app.state.appearance = appearance
    app.state.get_mode_status = _mode_status
    app.state.cancel_task = _cancel_task
    app.state.conversation = conversation
    app.state.supervisor = supervisor
    app.state.character_memories = character_memories
    app.state.character_switch = character_switch
    app.state.character_registry = character_registry
    app.state.active_pack = selected_pack
    clone = config.voice.tts.clone
    app.state.active_voice_profile = (
        VoiceProfileStore(config.app.data_dir).match_active(
            provider=clone.provider,
            voice_id=clone.voice_id,
            reference_path=clone.reference_path,
        )
        if clone is not None
        else None
    )
    app.state.memory = wiring.memory
    app.state.diagnostics = diagnostics

    speech_subscription = wiring.bus.subscribe()

    async def _consume_speech_turns() -> None:
        async for event in speech_subscription:
            if not isinstance(event, UserSpeechFinal):
                continue
            spoken = event.text.strip()
            if not event.accepted or not spoken or event.reason == "interrupted":
                continue
            await _handle_user_text(spoken, source=event.input_mode)

    async def _proactive_idle_loop() -> None:
        # BENNY_110E21E: settings are reloaded on each check, no restart required.
        import json as _proactive_json
        from datetime import datetime as _proactive_datetime
        _settings_path = Path(__file__).resolve().parents[4] / "config" / "proactive.json"
        _last_proactive_sent = 0.0
        while True:
            await asyncio.sleep(5)
            try:
                _settings = _proactive_json.loads(_settings_path.read_text(encoding="utf-8"))
                if not isinstance(_settings, dict):
                    continue
                _enabled = _settings.get("enabled", True)
                _idle = _settings.get("idle_seconds", 900)
                _cooldown = _settings.get("cooldown_seconds", 1800)
                _quiet_start = _settings.get("quiet_start_hour", 23)
                _quiet_end = _settings.get("quiet_end_hour", 8)
                if (type(_enabled) is not bool or type(_idle) not in (int, float)
                        or type(_cooldown) not in (int, float)
                        or type(_quiet_start) is not int or type(_quiet_end) is not int
                        or not 60 <= _idle <= 86400 or not 60 <= _cooldown <= 86400
                        or not 0 <= _quiet_start <= 23 or not 0 <= _quiet_end <= 23):
                    continue
                if not _enabled:
                    continue
                _hour = _proactive_datetime.now().hour  # Windows local time
                if _quiet_start != _quiet_end and (
                    (_quiet_start <= _hour < _quiet_end)
                    if _quiet_start < _quiet_end
                    else (_hour >= _quiet_start or _hour < _quiet_end)
                ):
                    continue
                _now = time.monotonic()
                elapsed = _now - proactive_idle["last_user_activity"]
                if elapsed < _idle or _now - _last_proactive_sent < _cooldown:
                    continue
            except (OSError, ValueError, TypeError, _proactive_json.JSONDecodeError):
                _log.warning("PROACTIVE_SETTINGS_INVALID: skipping check")
                continue
            if wiring.speech.is_speaking or wiring.speech.ptt_active:
                continue
            if getattr(wiring.speech.stt, "vad_active", False):
                continue
            if not supervisor.can_accept_turn:
                continue
            topics = (
                "自然關心使用者今日過得點，避免重複之前嘅問題。",
                "根據已知興趣或長期記憶，提出一條具體而輕鬆嘅問題；如果冇相關資料，就唔好猜測。",
                "分享一個輕鬆有趣嘅話題，邀請使用者一齊傾偈。",
                "如果有之前嘅對話內容，可以自然延續其中一個話題；否則提出一個新話題。",
            )
            topic = topics[proactive_idle["topic_index"] % len(topics)]
            followup = None
            try:
                followup = await wiring.memory.due_followup()
            except Exception:
                _log.warning("PROACTIVE_FOLLOWUP_LOOKUP_FAILED", exc_info=True)
            if followup is not None:
                topic = (
                    f"使用者之前講過 {followup.when.isoformat()} 有呢件事：「{followup.description}」。"
                    "自然咁關心下件事進行成點、結果如何或者佢有咩感受，唔好扮知道結果。"
                )
            recent_greetings = "\n".join(f"- {reply}" for reply in conversation.proactive_replies)
            if recent_greetings:
                topic += f"\n你最近已經講過以下說話，今次請避免重複相同問題或內容：\n{recent_greetings}"
            prompt = (
                f"今次主動聊天嘅話題方向：{topic}"
                "這是系統觸發的主動問候，不是使用者發言。"
                "請用自然、親切的香港廣東話主動同使用者傾偈，"
                "講一至兩句簡短說話，可以關心對方近況，"
                "或者根據已知興趣提出一條輕鬆問題。"
                "不要提及系統、計時器、提示詞，亦不要假裝使用者剛剛講過嘢。"
            )
            _log.info("PROACTIVE_TOPIC: index=%d recent_replies=%d", proactive_idle["topic_index"] % len(topics), len(conversation.proactive_replies))
            submission = await conversation.submit_background(prompt, source="proactive")
            if submission.accepted:
                proactive_idle["last_user_activity"] = time.monotonic()
                _last_proactive_sent = proactive_idle["last_user_activity"]
                if followup is not None:
                    with suppress(Exception):
                        await wiring.memory.mark_followed_up(followup.memory_id)
                    _log.info("PROACTIVE_EVENT_FOLLOWUP: %s", followup.memory_id)
                else:
                    proactive_idle["topic_index"] += 1
                _log.info("PROACTIVE_TURN_STARTED: idle %.0f seconds", elapsed)
    speech_turn_task = asyncio.create_task(
        _consume_speech_turns(), name="openmimicry.backend.speech_turns"
    )

    proactive_task = asyncio.create_task(_proactive_idle_loop(), name="openmimicry.backend.proactive_idle")

    async def _memory_maintenance_loop() -> None:
        # Phase 2: index memories at startup, then summarise idle conversations.
        with suppress(Exception):
            await wiring.memory.warm_up()
        try:
            imported = await novels.import_inbox()
            if imported:
                _log.info("NOVEL_INBOX %s", [(r["file"], r["status"]) for r in imported])
        except Exception:
            _log.warning("NOVEL_IMPORT_AT_STARTUP_FAILED", exc_info=True)
        while True:
            await asyncio.sleep(30)
            idle = time.monotonic() - proactive_idle["last_user_activity"]
            if idle >= config.memory.summary_idle_seconds and supervisor.can_accept_turn:
                _schedule_summary(force=True)

    memory_task = asyncio.create_task(
        _memory_maintenance_loop(), name="openmimicry.backend.memory_maintenance"
    )

    def _report_proactive_failure(task: asyncio.Task) -> None:
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            _log.error(
                "PROACTIVE_TASK_FAILED",
                exc_info=(type(error), error, error.__traceback__),
            )
        else:
            _log.warning("PROACTIVE_TASK_STOPPED unexpectedly")

    proactive_task.add_done_callback(_report_proactive_failure)
    await wiring.speech.start()
    if mode_state["continuous_listening"]:
        await wiring.speech.enable_continuous_listening()
    elif mode_state["live_wake"]:
        await wiring.speech.enable_live_listening(wake_names=None)
    await wiring.orchestrator.start()
    await supervisor.set_runtime_state("ready")
    await bridge.remember({"type": "runtime.state", **supervisor.snapshot()})
    # Windows that open later learn which companion (Benny / 叮當) is active.
    await bridge.remember(character_message(get_character(character_memories.active_id)))

    _mount_static_characters(app, config)

    try:
        yield
    finally:
        await supervisor.set_runtime_state("stopping", reason="application_shutdown")
        proactive_task.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await proactive_task
        memory_task.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await memory_task
        speech_turn_task.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await speech_turn_task
        await conversation.close()
        try:
            await asyncio.wait_for(_graceful_shutdown(wiring), timeout=2.0)
        except TimeoutError:
            _log.warning("backend lifespan: graceful shutdown exceeded 2s budget")
        finally:
            await supervisor.set_runtime_state("stopped", reason="application_shutdown")
            diagnostics.close()


async def _graceful_shutdown(wiring: Wiring) -> None:
    await asyncio.gather(
        wiring.orchestrator.stop(),
        wiring.speech.stop(),
        wiring.memory.close(),
        return_exceptions=True,
    )
    await wiring.runtime.stop()


def create_app() -> FastAPI:
    app = FastAPI(
        title="OpenMimicry Backend",
        version="1.6.4",
        lifespan=lifespan,
    )

    app.include_router(health_router)
    app.include_router(chat_router)
    app.include_router(characters_router)
    app.include_router(companions_router)
    app.include_router(dashboard_router)
    app.include_router(diagnostics_router)
    app.include_router(mode_router)
    app.include_router(llm_router)
    app.include_router(interaction_router)
    app.include_router(memory_router)
    app.include_router(novels_router)
    app.include_router(personality_router)
    app.include_router(voice_clone_router)
    app.include_router(voice_profiles_router)
    app.include_router(pack_router)
    app.include_router(admin_router)
    app.include_router(appearance_router)

    @app.websocket("/ws")
    async def _ws(websocket: WebSocket) -> None:
        wiring: Wiring = websocket.app.state.wiring
        bridge: BroadcastBridge = websocket.app.state.bridge
        handle_user_text = websocket.app.state.handle_user_text
        apply_mode_toggle = websocket.app.state.apply_mode_toggle
        get_mode_status = websocket.app.state.get_mode_status
        cancel_task = websocket.app.state.cancel_task
        await ws_endpoint(
            websocket,
            bus=wiring.bus,
            speech=wiring.speech,
            bridge=bridge,
            handle_user_text=handle_user_text,
            apply_mode_toggle=apply_mode_toggle,
            get_mode_status=get_mode_status,
            cancel_task=cancel_task,
        )

    return app


app = create_app()


def _mount_static_characters(app: FastAPI, config: AppConfig) -> None:
    """Mount the first existing ``avatar.pack_roots`` entry at ``/static/characters``."""
    for raw in config.avatar.pack_roots:
        root = Path(raw).expanduser()
        if root.is_dir():
            try:
                app.mount(
                    "/static/characters",
                    StaticFiles(directory=str(root)),
                    name="characters",
                )
            except Exception as exc:
                _log.warning("static-mount /static/characters failed: %s", exc)
            return
    _log.info("no avatar.pack_roots directory found; skipping static mount")


def run_uvicorn() -> None:  # pragma: no cover - script entry point
    """`openmimicry-backend` console script."""
    import uvicorn

    host = os.environ.get("OPENMIMICRY_HOST", "127.0.0.1")
    port = int(os.environ.get("OPENMIMICRY_PORT", "8000"))
    uvicorn.run(
        "openmimicry_backend.main:app",
        host=host,
        port=port,
        reload=False,
    )
