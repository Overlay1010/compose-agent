"""환경 설정. 값은 backend/.env 에서 읽는다 (.env는 git에 올리지 않는다, .env.example 참고)."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# 어떤 LLM을 쓸지: anthropic(Claude) | openai(OpenAI · Ollama · Gemini 등 같은 형식)
LLM_PROVIDER = (os.getenv("LLM_PROVIDER") or "anthropic").strip().lower()
ANTHROPIC_API_KEY = (os.getenv("ANTHROPIC_API_KEY") or "").strip() or None
ANTHROPIC_MODEL = (os.getenv("ANTHROPIC_MODEL") or "claude-sonnet-5-5").strip()

OPENAI_API_KEY = (os.getenv("OPENAI_API_KEY") or "").strip() or None
OPENAI_MODEL = (os.getenv("OPENAI_MODEL") or "gpt-5.4-mini").strip()
# OpenAI 호환 서버(Ollama, Gemini 등)를 쓸 때만 지정
OPENAI_BASE_URL = (os.getenv("OPENAI_BASE_URL") or "").strip() or None
# 추론 모델의 생각 정도 (minimal/low/medium/high). 비워 두면 모델 기본값
OPENAI_REASONING_EFFORT = (os.getenv("OPENAI_REASONING_EFFORT") or "").strip() or None
# 명령 하나에 LLM과 주고받는 최대 횟수 (무한 반복·비용 폭주 방지)
AGENT_MAX_STEPS = int(os.getenv("AGENT_MAX_STEPS", "6"))
# 프로젝트 저장 파일 (SQLite). 비워 두면 메모리에만 둔다 (서버를 다시 켜면 사라짐, 테스트용)
DB_PATH = (os.getenv("COMPOSE_DB_PATH", str(Path(__file__).resolve().parent.parent / "data" / "compose.db"))).strip() or None
