"""화성 분석: 조성(키) · 마디별 코드 · 로마숫자 · 화성 기능 (v0.2).

계산은 이 모듈이 하고, LLM은 결과를 설명하거나 고르기만 한다.
"""

from app.harmony.analyze import ChordSpan, HarmonyAnalysis, KeyInfo, analyze

__all__ = ["ChordSpan", "HarmonyAnalysis", "KeyInfo", "analyze"]
