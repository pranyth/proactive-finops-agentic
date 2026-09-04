"""Optional real LLM reasoning adapter with a safe evidence-only fallback."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

# A configured-but-dead endpoint used to cost every request a full probe plus a
# subprocess timeout, and still return the fallback text. Probe results are
# cached, and one hard failure parks the provider for a cooldown so the console
# degrades immediately instead of stalling on every question.
STATUS_TTL_SECONDS = 60.0
# Short enough that one slow generation does not lock the console out for the
# rest of a demo; long enough to stop a dead endpoint being retried per request.
FAILURE_COOLDOWN_SECONDS = 120.0
# The console fetches decisions first and only then asks for the written
# summary, so this timeout is paid in the background and can afford to be
# generous. A local 3B model behind the WSL->Windows bridge is usually 7-15s
# but a cold model load pushes well past that.
SUBPROCESS_TIMEOUT_SECONDS = 90

_lock = threading.Lock()
_status_cache: tuple[float, dict[str, str]] | None = None
_disabled_until = 0.0
_disabled_reason = ""


def _park_provider(reason: str) -> None:
    global _disabled_until, _disabled_reason, _status_cache
    with _lock:
        _disabled_until = time.monotonic() + FAILURE_COOLDOWN_SECONDS
        _disabled_reason = reason
        _status_cache = None


def reset_llm_state() -> None:
    """Clear the probe cache and cooldown. Used by tests and after config edits."""
    global _disabled_until, _disabled_reason, _status_cache
    with _lock:
        _disabled_until = 0.0
        _disabled_reason = ""
        _status_cache = None


# Kept deliberately short. The console renders this as a single lead paragraph
# above the decision cards, which already carry the per-item numbers, so a long
# answer duplicates the table and — on CPU inference — doubles the wait.
SYSTEM_PROMPT = """You are an enterprise FinOps analyst for cloud infrastructure
and managed AI services. Use only the supplied structured evidence. Never invent prices, usage, savings,
or service capabilities. Write ONE short paragraph of at most 60 words in plain
language: what to do, and the main quality or business risk. State a dollar
saving ONLY if one appears in the evidence, and copy that figure exactly; some
questions are about health or risk and carry no savings number, so do not mention
money at all for those, not even to say there is none. Never state a number that is not in the evidence.
Do not list every deployment and do not use bullet points or markdown headings;
the interface already shows each recommendation separately. Recommendations are
proposals and require approval before any Lambda action changes production."""


@dataclass
class LLMResult:
    text: str
    mode: str
    model: str
    error: str = ""


class LLMReasoner:
    """Calls OpenAI, Anthropic, or a local Ollama endpoint when configured."""

    def status(self) -> dict[str, str]:
        global _status_cache
        with _lock:
            if _disabled_until and time.monotonic() < _disabled_until:
                return self._parked_status()
            if _status_cache and time.monotonic() < _status_cache[0]:
                return dict(_status_cache[1])

        result = self._probe_status()
        with _lock:
            _status_cache = (time.monotonic() + STATUS_TTL_SECONDS, dict(result))
        return result

    def _parked_status(self) -> dict[str, str]:
        provider = os.getenv("FINOPS_LLM_PROVIDER", "auto").lower()
        return {
            "provider": provider,
            "model": self._model(provider),
            "mode": "evidence_policy_fallback",
            "configured": "true",
            "reachable": "false",
            "detail": _disabled_reason,
        }

    def _probe_status(self) -> dict[str, str]:
        provider = os.getenv("FINOPS_LLM_PROVIDER", "auto").lower()
        if provider == "auto":
            if os.getenv("OPENAI_API_KEY"):
                provider = "openai"
            elif os.getenv("ANTHROPIC_API_KEY"):
                provider = "anthropic"
            elif os.getenv("OLLAMA_MODEL"):
                provider = "ollama"
            else:
                provider = "policy_fallback"
        model = self._model(provider)
        reachable = provider != "ollama" or self._ollama_reachable()
        return {
            "provider": provider,
            "model": model,
            "mode": "llm" if provider != "policy_fallback" and reachable else "evidence_policy_fallback",
            "configured": str(provider != "policy_fallback").lower(),
            "reachable": str(reachable).lower(),
        }

    def explain(self, question: str, evidence: dict[str, Any], fallback: str) -> LLMResult:
        status = self.status()
        provider = status["provider"]
        if provider == "policy_fallback":
            return LLMResult(fallback, "evidence_policy_fallback", "none")
        if status["mode"] != "llm":
            return LLMResult(fallback, "evidence_policy_fallback", self._model(provider), "Configured LLM endpoint is unreachable")
        prompt = (
            f"User question: {question}\n\n"
            f"Structured evidence:\n{json.dumps(evidence, indent=2, default=str)}\n\n"
            f"Validated baseline answer:\n{fallback}"
        )
        try:
            if provider == "openai":
                text = self._openai(prompt)
            elif provider == "anthropic":
                text = self._anthropic(prompt)
            elif provider == "ollama":
                text = self._ollama(prompt)
            else:
                raise ValueError(f"Unsupported FINOPS_LLM_PROVIDER: {provider}")
            return LLMResult(text.strip(), "llm", self._model(provider))
        except Exception as exc:
            # Park the provider so the next question falls back instantly rather
            # than paying the same timeout again.
            _park_provider(f"{provider} unavailable: {exc}")
            return LLMResult(fallback, "evidence_policy_fallback", self._model(provider), str(exc))

    def _model(self, provider: str) -> str:
        return {
            "openai": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            "anthropic": os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-latest"),
            "ollama": os.getenv("OLLAMA_MODEL", "llama3.2:3b"),
            "policy_fallback": "none",
        }.get(provider, "unknown")

    def _ollama_reachable(self) -> bool:
        cli_path = os.getenv("OLLAMA_CLI_PATH", "")
        powershell_path = os.getenv("OLLAMA_POWERSHELL_PATH", "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
        return self._ollama_http_reachable() or os.path.exists(powershell_path) or bool(cli_path and os.path.exists(cli_path))

    def _ollama_http_reachable(self) -> bool:
        base = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
        try:
            with urllib.request.urlopen(f"{base}/api/tags", timeout=1):
                return True
        except (OSError, urllib.error.URLError):
            return False

    def _ollama_payload(self, prompt: str) -> dict[str, Any]:
        """One payload for both transports; they used to disagree on num_predict.

        `think: false` matters a lot on CPU. A reasoning model like qwen3 will
        otherwise spend the whole token budget on hidden reasoning and return a
        truncated summary — measured 11.0s and cut off mid-sentence with it on,
        4.8s and complete with it off. Ollama ignores the flag for models that
        do not reason, so it is safe to always send.
        """
        return {
            "model": self._model("ollama"),
            "stream": False,
            "think": os.getenv("OLLAMA_THINK", "false").lower() == "true",
            # Ollama evicts an idle model after ~5 minutes, and reloading it
            # costs more than the generation itself. Hold it resident so the
            # second question in a demo is not the slow one.
            "keep_alive": os.getenv("OLLAMA_KEEP_ALIVE", "30m"),
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "options": {
                "temperature": 0.1,
                "num_predict": int(os.getenv("OLLAMA_NUM_PREDICT", "110")),
            },
        }

    def _ollama_windows_api(self, prompt: str) -> str:
        powershell_path = os.getenv("OLLAMA_POWERSHELL_PATH", "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
        command = (
            "$body = [Console]::In.ReadToEnd(); "
            "$response = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/chat' "
            "-Method Post -ContentType 'application/json' -Body $body; "
            "$response | ConvertTo-Json -Depth 20 -Compress"
        )
        payload = self._ollama_payload(prompt)
        result = subprocess.run(
            [powershell_path, "-NoProfile", "-NonInteractive", "-Command", command],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
            check=True,
        )
        data = json.loads(result.stdout)
        return data["message"]["content"]
    def _request(self, url: str, payload: dict[str, Any], headers: dict[str, str], timeout: int = SUBPROCESS_TIMEOUT_SECONDS) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", **headers},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def _openai(self, prompt: str) -> str:
        base = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        data = self._request(
            f"{base}/chat/completions",
            {
                "model": self._model("openai"),
                "temperature": 0.1,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            },
            {"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
        )
        return data["choices"][0]["message"]["content"]

    def _anthropic(self, prompt: str) -> str:
        data = self._request(
            "https://api.anthropic.com/v1/messages",
            {
                "model": self._model("anthropic"),
                "max_tokens": 300,
                "temperature": 0.1,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": prompt}],
            },
            {
                "x-api-key": os.environ["ANTHROPIC_API_KEY"],
                "anthropic-version": "2023-06-01",
            },
        )
        return data["content"][0]["text"]

    def _ollama(self, prompt: str) -> str:
        base = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
        if not self._ollama_http_reachable():
            powershell_path = os.getenv("OLLAMA_POWERSHELL_PATH", "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
            if os.path.exists(powershell_path):
                return self._ollama_windows_api(prompt)
            cli_path = os.getenv("OLLAMA_CLI_PATH", "")
            if not cli_path or not os.path.exists(cli_path):
                raise ConnectionError("Ollama HTTP API and CLI are both unavailable")
            cli_prompt = f"{SYSTEM_PROMPT}\n\n{prompt}"
            result = subprocess.run(
                [cli_path, "run", "--nowordwrap", self._model("ollama"), cli_prompt],
                capture_output=True,
                text=True,
                timeout=SUBPROCESS_TIMEOUT_SECONDS,
                check=True,
            )
            return result.stdout.strip()

        data = self._request(f"{base}/api/chat", self._ollama_payload(prompt), {})
        return data["message"]["content"]

