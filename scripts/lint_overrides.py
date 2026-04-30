"""CATEGORY_OVERRIDES 가 cover 하는 source 가 어댑터에서 apply_override 호출되는지 검사.

audit P1-2 (2026-04-25) 응답 — override 신규 추가 시 어댑터 호출 누락 자동 감지 / CI 가드.
Lint check: every source declared in CATEGORY_OVERRIDES must be handled by an adapter
that imports & calls apply_override. Returns exit 1 on missing coverage.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sources._classification_overrides import CATEGORY_OVERRIDES


def main() -> int:
    override_sources = sorted({src for (src, _sid) in CATEGORY_OVERRIDES.keys()})
    adapter_files = [p for p in (ROOT / "sources").glob("*.py") if not p.name.startswith("_")]

    source_to_files: dict[str, list[Path]] = {s: [] for s in override_sources}
    for f in adapter_files:
        content = f.read_text(encoding="utf-8")
        declared = set(re.findall(
            r'(?:^|\n)\s*(?:SOURCE|source|SRC)\s*=\s*[\'"]([a-z_][a-z0-9_]*)[\'"]',
            content,
        ))
        for s in declared & set(override_sources):
            source_to_files[s].append(f)

    errors: list[str] = []
    for source, files in source_to_files.items():
        if not files:
            errors.append(
                f"❌ override source '{source}' 를 선언한 어댑터 파일이 없음 "
                f"(어댑터에서 SOURCE='{source}' 선언 필요)"
            )
            continue
        for f in files:
            if "apply_override" not in f.read_text(encoding="utf-8"):
                errors.append(
                    f"❌ {f.name}: SOURCE='{source}' 처리하는데 apply_override 미호출"
                )

    if errors:
        for e in errors:
            print(e, file=sys.stderr)
        print(f"\n총 {len(errors)}건 — CATEGORY_OVERRIDES 누락 / Missing", file=sys.stderr)
        return 1

    print(f"✅ override sources {override_sources} 모두 어댑터에서 apply_override 호출됨")
    return 0


if __name__ == "__main__":
    sys.exit(main())
