"""환경 설정. 값은 backend/.env 에서 읽는다 (.env는 git에 올리지 않는다, .env.example 참고)."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

OPENAI_API_KEY = (os.getenv("OPENAI_API_KEY") or "").strip() or None
OPENAI_MODEL = (os.getenv("OPENAI_MODEL") or "gpt-5.4-mini").strip()
# OpenAI 호환 서버(Ollama, Gemini 등)를 쓸 때만 지정
OPENAI_BASE_URL = (os.getenv("OPENAI_BASE_URL") or "").strip() or None
# 추론 모델의 생각 정도 (minimal/low/medium/high). 비워 두면 모델 기본값
OPENAI_REASONING_EFFORT = (os.getenv("OPENAI_REASONING_EFFORT") or "").strip() or None
# 명령 하나에 LLM과 주고받는 최대 횟수 (무한 반복·비용 폭주 방지)
AGENT_MAX_STEPS = int(os.getenv("AGENT_MAX_STEPS", "6"))
