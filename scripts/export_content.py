"""content/{yyyy-mm}/{slug}.md → frontend/public/data/content/ JSON export.

Step 2 Wave 1 — markdown + frontmatter 를 정적 JSON 으로 빌드.
- index.json: list 메타 (페이지네이션·필터링용)
- {slug}.json: 메타 + html (per-content)

frontmatter spec (YAML):
    slug, title, persona (optional), area_codes (list), poi_refs (list[int]),
    ai_assisted (bool), ai_disclosure (string|null), hero_image, excerpt,
    tags (list), status (draft|published|archived), published_at, updated_at

draft / archived 는 export 제외 (status=published 만).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import markdown
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONTENT_DIR = ROOT / "content"
OUT_DIR = ROOT / "frontend" / "public" / "data" / "content"

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


def parse_post(path: Path) -> dict | None:
    raw = path.read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(raw)
    if not m:
        print(f"[content] {path}: frontmatter 누락 — skip", file=sys.stderr)
        return None
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        print(f"[content] {path}: YAML error — {e}", file=sys.stderr)
        return None
    body_md = m.group(2)
    if not isinstance(meta.get("slug"), str):
        print(f"[content] {path}: slug 누락 — skip", file=sys.stderr)
        return None
    if meta.get("status") != "published":
        return None
    md = markdown.Markdown(extensions=["extra", "sane_lists", "smarty"])
    body_html = md.convert(body_md)
    return {
        "slug": meta["slug"],
        "title": meta.get("title", ""),
        "persona": meta.get("persona"),
        "area_codes": meta.get("area_codes") or [],
        "poi_refs": meta.get("poi_refs") or [],
        "ai_assisted": bool(meta.get("ai_assisted")),
        "ai_disclosure": meta.get("ai_disclosure"),
        "hero_image": meta.get("hero_image"),
        "excerpt": meta.get("excerpt") or "",
        "tags": meta.get("tags") or [],
        "published_at": _isoformat(meta.get("published_at")),
        "updated_at": _isoformat(meta.get("updated_at")),
        "html": body_html,
        "_path": str(path.relative_to(ROOT)),
    }


def _isoformat(v) -> str | None:
    if v is None:
        return None
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return str(v)


def main() -> int:
    if not CONTENT_DIR.exists():
        print(f"[content] {CONTENT_DIR} 미존재 — skip", file=sys.stderr)
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUT_DIR / "index.json").write_text(
            json.dumps({"count": 0, "items": []}, ensure_ascii=False),
            encoding="utf-8",
        )
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    posts: list[dict] = []
    for md_path in sorted(CONTENT_DIR.rglob("*.md")):
        post = parse_post(md_path)
        if post:
            posts.append(post)

    posts.sort(key=lambda p: p.get("published_at") or "", reverse=True)

    # per-slug 파일 — html 포함
    for p in posts:
        (OUT_DIR / f"{p['slug']}.json").write_text(
            json.dumps(p, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )

    # index — 리스트용 요약 (html 제외)
    index_items = [
        {k: v for k, v in p.items() if k != "html" and not k.startswith("_")}
        for p in posts
    ]
    (OUT_DIR / "index.json").write_text(
        json.dumps(
            {"count": len(index_items), "items": index_items},
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )

    print(f"[content] exported {len(posts)} posts → {OUT_DIR.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
