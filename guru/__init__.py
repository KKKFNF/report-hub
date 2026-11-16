"""투자구루 판단의견(hub:guru) — 리서치 리포트 허브용 룰+LLM 하이브리드 의견 블록 생성기."""
from .config import BLOCK_VERSION, PROMPT_VERSION, RULES_VERSION

__all__ = ["RULES_VERSION", "PROMPT_VERSION", "BLOCK_VERSION"]
__version__ = RULES_VERSION
