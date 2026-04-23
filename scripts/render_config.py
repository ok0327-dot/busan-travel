"""
.env → frontend/public/config.js 생성.

단일 소스(.env) 에서 브라우저용 config.js 를 빌드. config.js 는 gitignored.
키 변경 시 .env 만 수정하고 이 스크립트 실행하면 됨.

사용법: python scripts/render_config.py
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
ENV_PATH = ROOT / ".env"
OUT_PATH = ROOT / "frontend" / "public" / "config.js"


def main() -> int:
    if not ENV_PATH.exists():
        print(f"[render_config] ERROR: {ENV_PATH} 없음. .env.example 참고해서 생성 필요.")
        return 1
    load_dotenv(ENV_PATH)

    key = os.environ.get("KAKAO_JS_KEY")
    if not key:
        print("[render_config] ERROR: KAKAO_JS_KEY 가 .env 에 없음.")
        return 1

    content = f"""// AUTO-GENERATED from .env by scripts/render_config.py — 직접 편집하지 말 것.
// 키 바꾸려면 .env 를 수정하고 `python scripts/render_config.py` 재실행.
window.APP_CONFIG = {{
  KAKAO_JS_KEY: {key!r},
  BUSAN_CENTER: {{ lat: 35.1796, lon: 129.0756 }},
  DEFAULT_LEVEL: 8,
}};
"""
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(content, encoding="utf-8")
    print(f"[render_config] OK → {OUT_PATH} (key prefix={key[:8]}…)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
