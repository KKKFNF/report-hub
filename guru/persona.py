"""
LLM 정성 필터(버핏·멍거·드러켄밀러).

- 입력: 익명화된 지표 패킷 + 익명화된 리포트 발췌
- 출력: 고정 스키마 JSON (룰 점수와 섞지 않고 블록의 별도 열에 표기)
- 백엔드: GURU_LLM_BACKEND = anthropic | command | none
    anthropic : Anthropic Messages API (ANTHROPIC_API_KEY, GURU_LLM_MODEL), temperature 0
    command   : GURU_LLM_CMD 에 지정한 셸 명령에 프롬프트를 stdin 으로 넘기고 stdout 의 JSON 을 읽음
                (예: OpenClaw/Claude CLI  `claude -p --output-format text`)
    none      : 호출하지 않음(룰만)
- 캐시: (프롬프트 버전, 페르소나, 패킷 해시) → ~/.guru/cache/llm/<sha>.json  (재실행 시 비용 0)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import urllib.request
from typing import Dict, Optional

from . import config as C

PROMPT_DIR = os.path.join(os.path.dirname(__file__), "prompts")
REQUIRED = {
    "buffett": ["moat", "capital_allocation", "verdict", "confidence", "one_line"],
    "munger": ["how_it_fails", "predictability", "verdict", "confidence", "one_line"],
    "druckenmiller": ["change_thesis", "asymmetry", "verdict", "confidence", "one_line"],
}


class LLMError(RuntimeError):
    pass


def load_prompt(persona: str) -> str:
    with open(os.path.join(PROMPT_DIR, f"{persona}.md"), encoding="utf-8") as fh:
        return fh.read()


def build_prompt(persona: str, metrics: dict, excerpt: str) -> str:
    tpl = load_prompt(persona)
    out = tpl.replace("{metrics}", json.dumps(metrics, ensure_ascii=False, indent=1)).replace("{excerpt}", excerpt)
    return out.replace("{{", "{").replace("}}", "}")   # 프롬프트 파일의 JSON 예시는 {{ }} 로 이스케이프되어 있음


def _extract_json(text: str) -> dict:
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise LLMError("응답에 JSON 없음: " + text[:200])
    blob = m.group(0)
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        # 코드펜스 제거 재시도
        blob = re.sub(r"```(?:json)?", "", blob)
        return json.loads(blob)


class LLMClient:
    def __init__(self, backend: Optional[str] = None, model: Optional[str] = None,
                 cache_dir: Optional[str] = None, command: Optional[str] = None):
        self.backend = (backend or os.environ.get("GURU_LLM_BACKEND") or "none").lower()
        self.model = model or os.environ.get("GURU_LLM_MODEL") or C.LLM["default_model"]
        self.command = command or os.environ.get("GURU_LLM_CMD", "")
        self.cache = os.path.expanduser(cache_dir or os.environ.get("GURU_LLM_CACHE") or C.LLM["cache_dir"])
        os.makedirs(self.cache, exist_ok=True)
        self.calls = 0

    def _cache_key(self, persona: str, prompt: str) -> str:
        h = hashlib.sha256()
        h.update((C.PROMPT_VERSION + "|" + persona + "|" + self.model + "|" + self.backend + "|").encode())
        h.update(prompt.encode("utf-8"))
        return h.hexdigest()

    def _call_anthropic(self, prompt: str) -> str:
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            raise LLMError("ANTHROPIC_API_KEY 없음")
        body = {
            "model": self.model,
            "max_tokens": C.LLM["max_tokens"],
            "temperature": C.LLM["temperature"],
            "messages": [{"role": "user", "content": prompt}],
        }
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps(body).encode("utf-8"),
            headers={"content-type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"},
        )
        with urllib.request.urlopen(req, timeout=90) as r:
            data = json.loads(r.read().decode("utf-8"))
        parts = [c.get("text", "") for c in data.get("content", []) if c.get("type") == "text"]
        return "\n".join(parts)

    def _call_command(self, prompt: str) -> str:
        if not self.command:
            raise LLMError("GURU_LLM_CMD 없음")
        proc = subprocess.run(self.command, input=prompt, capture_output=True, text=True, shell=True, timeout=240)
        if proc.returncode != 0:
            raise LLMError(f"명령 실패({proc.returncode}): {proc.stderr[:300]}")
        return proc.stdout

    def ask(self, persona: str, metrics: dict, excerpt: str) -> Optional[dict]:
        if self.backend == "none":
            return None
        prompt = build_prompt(persona, metrics, excerpt)
        key = self._cache_key(persona, prompt)
        path = os.path.join(self.cache, key + ".json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        if self.backend == "anthropic":
            raw = self._call_anthropic(prompt)
        elif self.backend == "command":
            raw = self._call_command(prompt)
        else:
            raise LLMError(f"알 수 없는 백엔드 {self.backend}")
        self.calls += 1
        out = _extract_json(raw)
        for k in REQUIRED[persona]:
            if k not in out:
                raise LLMError(f"{persona} 응답에 '{k}' 누락")
        if out.get("verdict") not in ("적합", "보류", "부적합"):
            out["verdict"] = "보류"
        try:
            out["confidence"] = max(0.0, min(1.0, float(out.get("confidence", 0.0))))
        except (TypeError, ValueError):
            out["confidence"] = 0.0
        out["_meta"] = {"model": self.model, "backend": self.backend, "prompt_version": C.PROMPT_VERSION, "cache_key": key[:12]}
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, indent=1)
        return out


def run_personas(client: LLMClient, metrics: dict, excerpt: str, personas=None) -> Dict[str, Optional[dict]]:
    out: Dict[str, Optional[dict]] = {}
    for p in (personas or C.LLM["personas"]):
        try:
            out[p] = client.ask(p, metrics, excerpt)
        except Exception as e:  # noqa — LLM 실패가 룰 결과를 막지 않게 한다
            out[p] = {"error": str(e)[:200]}
    return out
