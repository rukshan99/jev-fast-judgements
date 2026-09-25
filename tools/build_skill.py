#!/usr/bin/env python3
"""Package the skill for upload to claude.ai / Claude Desktop (Customize > Skills).

Writes dist/jev-fast-judgements.zip containing the jev-fast-judgements/ folder.
Usage: python tools/build_skill.py
"""
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "skills" / "jev-fast-judgements"
OUT = ROOT / "dist" / f"{SKILL_DIR.name}.zip"
SKIP_DIRS = {"__pycache__", ".pytest_cache"}
SKIP_FILES = {".DS_Store"}

OUT.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as zf:
    for path in sorted(SKILL_DIR.rglob("*")):
        rel = path.relative_to(SKILL_DIR)
        if path.is_dir() or SKIP_DIRS & set(rel.parts) or path.name in SKIP_FILES:
            continue
        zf.write(path, Path(SKILL_DIR.name) / rel)
print(f"Built {OUT.relative_to(ROOT)} ({OUT.stat().st_size:,} bytes)")
