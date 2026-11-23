"""OpenRouter chat completions (OpenAI-compatible API)."""

from __future__ import annotations

from typing import Any

import httpx


class LLMError(RuntimeError):
    pass


class OpenRouter:
    def __init__(self, api_key: str, url: str, *, timeout_s: float = 90.0) -> None:
        self._key = api_key
        self._url = url
        self._client = httpx.AsyncClient(timeout=timeout_s)

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        json_mode: bool = False,
        temperature: float = 0.6,
        max_tokens: int = 600,
    ) -> str:
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        response = await self._client.post(
            self._url,
            json=body,
            headers={
                "Authorization": f"Bearer {self._key}",
                "X-Title": "Benny companion (web)",
            },
        )
        if response.status_code >= 400:
            raise LLMError(f"OpenRouter {response.status_code}: {response.text[:300]}")
        data = response.json()
        try:
            return str(data["choices"][0]["message"]["content"] or "")
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"unexpected OpenRouter payload: {str(data)[:300]}") from exc

    async def close(self) -> None:
        await self._client.aclose()


class HelperCompletion:
    """The ``complete(prompt)`` surface used by memory extraction and summaries."""

    def __init__(self, llm: OpenRouter, model: str, system: str) -> None:
        self._llm = llm
        self._model = model
        self._system = system

    async def complete(self, prompt: str) -> str:
        return await self._llm.chat(
            [{"role": "system", "content": self._system}, {"role": "user", "content": prompt}],
            model=self._model,
            temperature=0.0,
            max_tokens=500,
        )
