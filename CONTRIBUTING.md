# Contributing

Thanks for helping improve `jev-fast-judgements`. Recipes from real investigations are especially welcome.

## Ground rules

- **The runner stays standard-library only.** `skills/jev-fast-judgements/scripts/jev.py` must run anywhere Python 3.9+ runs, with nothing to install.
- **SKILL.md stays short.** It's loaded into the agent's context every time the skill triggers, so keep it under 500 lines. Put detail in `references/` and point to it from SKILL.md.
- **Explain why, not just what.** The agent follows guidance better when it understands the reason behind a rule.
- **No secrets or private data** in examples, tests or issues.

## Development

```bash
git clone https://github.com/rukshan99/jev-fast-judgements.git
cd jev-fast-judgements
python tools/validate.py                      # frontmatter, manifests, versions
python -m unittest discover -s tests -v       # offline, uses a mock API, no key needed
python tools/build_skill.py                   # dist/jev-fast-judgements.zip for claude.ai upload
```

To try the skill in Claude Code while you edit, without installing it:

```bash
claude --plugin-dir .
```

Or register your working copy as a local marketplace:

```bash
claude plugin marketplace add ./
claude plugin install jev-fast-judgements@jev-fast-judgements
```

Then run `/reload-plugins` after each edit.

## Adding a playbook recipe

1. Add a numbered section to `references/playbook.md`. Include the questions JSON, a command, and a short "then you..." explaining what the agent does with the output.
2. Test the questions against real material using `--dry-run` first, then a live key. Spot-check a few kept and a few dropped items.
3. If the recipe is common enough to matter, add a row to the "Where it pays off" table in `SKILL.md`.

## Releasing

1. Bump the version in `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`, and add a `CHANGELOG.md` entry.
2. Merge to `main`, then tag: `git tag v0.2.0 && git push origin v0.2.0`.
3. The Release workflow builds `jev-fast-judgements.zip` and attaches it to the GitHub release.
