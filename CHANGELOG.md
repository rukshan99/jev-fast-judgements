# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-09-25

### Added
- `jev-fast-judgements` skill: decision rules for when a System 2 agent should hand
  bulk, bounded judgments to TypeSafe's Jev, plus a six-step workflow.
- `scripts/jev.py`: standard-library runner with `ask`, `each` and `pack` modes,
  directory chunking, automatic request splitting, retries with backoff, `--dry-run`
  cost estimates, and a compact KEPT / UNSURE / DROPPED report.
- `references/playbook.md`: ten investigation recipes with ready-to-edit questions.
- `references/question-design.md`: question-writing rules, known weak spots and
  threshold guidance.
- Claude Code plugin marketplace manifests, offline test suite, CI and release workflows.

[Unreleased]: https://github.com/rukshan99/jev-fast-judgements/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/rukshan99/jev-fast-judgements/releases/tag/v0.1.0
