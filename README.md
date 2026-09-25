# jev-fast-judgements

[![CI](https://github.com/rukshan99/jev-fast-judgements/actions/workflows/ci.yml/badge.svg)](https://github.com/rukshan99/jev-fast-judgements/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

An [Agent Skill](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview) that teaches Claude, or any skills-compatible agent, **when and how to hand bulk, bounded judgments to [TypeSafe's Jev](https://docs.typesafe.ai)** during investigations. The goal is fewer tokens spent, faster answers, and the agent's own reasoning focused on what matters.

You don't operate Jev yourself. You investigate as usual, and the agent decides when a sub-task fits Jev, writes the questions, runs them, and reads back only a short verdict table.

## Why

Investigations are full of small judgments over large amounts of material. Is this search result relevant? Which of these 800 log lines matter? Does this passage support the claim? Is this web page trying to inject instructions? A reasoning model can answer all of these, but it has to read everything first, which is slow and costs tokens.

Jev is a *System One* model: it returns only calibrated probabilities, a choice from options you define, or a position on a scale you describe. It never writes prose. According to TypeSafe, most calls take about 100 ms, input costs $0.042 per million tokens, and output is free. This skill pairs the two models:

```
             agent (System 2)                        Jev (System 1)
  ┌───────────────────────────────┐        ┌───────────────────────────┐
  │ 1. saves material to disk     │        │                           │
  │ 2. writes a few questions ────┼──────▶ │ judges every item in      │
  │                               │  files │ parallel against the same │
  │ 4. reads only the verdicts ◀──┼─────── │ questions                 │
  │    KEPT · UNSURE · DROPPED    │ table  │                           │
  │ 5. reads KEPT + UNSURE items, │        └───────────────────────────┘
  │    reasons, writes the answer │
  └───────────────────────────────┘
```

The bulk text goes from disk to Jev without passing through the agent's context. The agent reads the few items that survive the filter, plus the ones Jev was unsure about, which the agent always handles itself.

## What's inside

| Path | Purpose |
|---|---|
| `skills/jev-fast-judgements/SKILL.md` | Decision rules (when to use Jev, and when not to), a six-step workflow, commands, and question-writing rules |
| `skills/jev-fast-judgements/scripts/jev.py` | Runner using only the Python standard library, with `ask`, `each` and `pack` modes |
| `skills/jev-fast-judgements/references/playbook.md` | Ten investigation recipes with ready-to-edit questions |
| `skills/jev-fast-judgements/references/question-design.md` | Question structure, known weak spots of Jev, and threshold guidance |
| `.claude-plugin/` | Claude Code plugin and marketplace manifests |
| `tests/`, `tools/` | Offline test suite with a mock API, validation, and zip packaging |

The recipes cover: relevance filtering, usefulness ranking, bulk labeling, claim support and contradiction checks, verifying the agent's own draft, prompt-injection screening, finding the lines that answer a question, entity matching, choosing what to open next, and extraction by picking from candidates.

## Install

### Claude Code (plugin marketplace)

```bash
claude plugin marketplace add rukshan99/jev-fast-judgements
claude plugin install jev-fast-judgements@jev-fast-judgements
```

Inside a session, the equivalents are `/plugin marketplace add rukshan99/jev-fast-judgements` and `/plugin install jev-fast-judgements@jev-fast-judgements`.

### Other agents (skills CLI)

For Codex, Cursor, OpenCode and other agents that read skill folders:

```bash
npx skills add rukshan99/jev-fast-judgements --skill jev-fast-judgements
```

### Manual

Copy `skills/jev-fast-judgements/` into your agent's skills directory. For Claude Code, that's `~/.claude/skills/` for a personal install or `.claude/skills/` inside a project.

### claude.ai, Claude Desktop and Cowork

1. Download `jev-fast-judgements.zip` from the [latest release](https://github.com/rukshan99/jev-fast-judgements/releases/latest).
2. Go to **Customize → Skills**, click **+**, then **Create skill**, and upload the zip. Code execution must be enabled.
3. The code sandbox needs to be allowed to reach `api.typesafe.ai` (or your gateway). If your plan or organization restricts outbound domains, add it to the allowlist.

> This surface is experimental. The sandbox has no persistent environment variables, so you'd have to provide the API key during the session, which is less safe than a shell variable. Claude Code and other local agents are the recommended setup.

## Setup

Get an API key from the [TypeSafe console](https://console.typesafe.ai) and export it in the shell your agent runs in:

```bash
export TYPESAFE_API_KEY=...            # required
export TYPESAFE_MODEL=jev-1.13.0       # optional: pin a version for stable thresholds
export TYPESAFE_BASE_URL=...           # optional: any /v1/systemone-compatible gateway
```

If TypeSafe's direct signups are closed, several gateways accept the same request format, so pointing `TYPESAFE_BASE_URL` at one of them works without other changes. Check each gateway's docs for its base URL and key.

Without a key or network access, the skill tells you once and the agent carries on by reading the material itself. The investigation never stalls on Jev.

## Usage

Investigate normally. The skill triggers when a task involves many small judgments over a lot of material. Some examples of prompts where it applies:

- *"Go through these 60 vendor pages and find which ones mention SOC 2 Type II, with evidence."*
- *"Here's last week's app log. What failed that users would have noticed?"*
- *"Check every claim in my draft report against the cited sources."*
- *"Deduplicate these two customer lists."*

A typical run the agent performs, and the kind of output it reads back:

```bash
python3 skills/jev-fast-judgements/scripts/jev.py each --dir ./pages --glob "*.md" \
  -q q_relevance.json --context "What caused the March outage?" \
  --sort relevant --keep "relevant>=0.5" --top 10 --preview 60
```

```
# jev each: 212 items answered, 212 calls, model jev-1.13.0
# jev input tokens 243,118 (~$0.0102); ~231,940 tokens of item text stayed out of your context. Full answers: jev_results.jsonl
## KEPT 14 (showing 10) - keep: relevant>=0.5
postmortem.md#0  relevant=0.97  | Postmortem: the March outage was caused by a config push…
...
## UNSURE 5 - not kept, but Jev was uncertain: read these yourself
## DROPPED 193 (confident no; details in jev_results.jsonl)
```

The numbers above are illustrative. Run `jev.py --help`, or read section 4 of `SKILL.md`, for every option. `--dry-run` shows the request count and estimated cost without calling the API.

## When the skill tells the agent *not* to use Jev

- Writing, summarizing, explaining or synthesizing. Jev doesn't generate text.
- Arithmetic, counting, and comparing dates, versions or amounts. These belong in code.
- Multi-step reasoning, or facts that aren't in the supplied text.
- Images, audio and video. Jev reads text only.
- A handful of short items, where just reading them is cheaper.

## Data and privacy

Item text is sent to TypeSafe's API, or to the gateway you configure. The skill tells the agent never to send credentials, and to confirm with you before sending confidential or personal data for the first time in a conversation. See [SECURITY.md](SECURITY.md) for details.

## Limitations

- Jev launched in September 2026 and is evolving quickly. Speed, cost and accuracy figures are TypeSafe's own.
- Calibration holds across many items, not for any single answer. The skill therefore has the agent spot-check results and read uncertain items itself.
- The test suite runs against an offline mock, so it verifies the script's plumbing, not Jev's judgment quality. Validate question sets on your own data.

## Development

```bash
python tools/validate.py                    # skill frontmatter, manifests, versions
python -m unittest discover -s tests -v     # offline tests, no key required
python tools/build_skill.py                 # builds dist/jev-fast-judgements.zip
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines and the release process.

## Disclaimer

This is an independent community project. It is not affiliated with, endorsed by, or sponsored by TypeSafe AI or Anthropic. "Jev" and "TypeSafe" are names of their respective owners. Use of the Jev API is subject to TypeSafe's terms.

## License

[MIT](LICENSE)
