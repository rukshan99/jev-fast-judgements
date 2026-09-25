#!/usr/bin/env python3
"""Repository checks run in CI: skill frontmatter, manifest consistency, versions.

Usage: python tools/validate.py
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "skills" / "jev-fast-judgements"
errors = []


def check(cond, msg):
    if not cond:
        errors.append(msg)


# SKILL.md frontmatter (Agent Skills format: name <= 64 chars kebab-case, description <= 1024)
text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
check(m is not None, "SKILL.md: missing YAML frontmatter")
front = dict(re.findall(r"^(\w[\w-]*):\s*(.*)$", m.group(1), re.M)) if m else {}
name, desc = front.get("name", ""), front.get("description", "")
check(re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name or "") and len(name) <= 64,
      f"SKILL.md: invalid name {name!r}")
check(name == SKILL_DIR.name, f"SKILL.md: name {name!r} must match folder {SKILL_DIR.name!r}")
check(0 < len(desc) <= 1024, f"SKILL.md: description length {len(desc)} (must be 1..1024)")
check("<" not in desc and ">" not in desc, "SKILL.md: description must not contain angle brackets")
check(len(text.splitlines()) <= 500, "SKILL.md: keep under 500 lines (move detail to references/)")

# Files the skill body points to must exist
for ref in sorted(set(re.findall(r"`((?:references|scripts)/[\w./-]+)`", text))):
    check((SKILL_DIR / ref).exists(), f"SKILL.md references missing file: {ref}")

# Manifests agree on name and version
plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
entry = next((p for p in market.get("plugins", []) if p.get("name") == plugin["name"]), None)
check(entry is not None, "marketplace.json: no plugin entry matching plugin.json name")
check(plugin["name"] == name, "plugin.json name must match the skill name")
for field in ("name", "owner", "plugins"):
    check(field in market, f"marketplace.json: missing required field {field!r}")
if entry:
    check(entry.get("source") == "./", "marketplace.json: entry source should be './'")
    check(entry.get("version") == plugin.get("version"), "marketplace.json and plugin.json versions differ")

# CHANGELOG mentions the current version
changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
check(f"[{plugin.get('version')}]" in changelog, f"CHANGELOG.md has no entry for {plugin.get('version')}")

if errors:
    print("Validation failed:")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
print(f"OK: {name} v{plugin.get('version')}")
