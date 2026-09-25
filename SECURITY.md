# Security policy

## Reporting a vulnerability

Please don't open a public issue for security problems. Report them privately through
**GitHub → Security → Report a vulnerability** on this repository. Include steps to
reproduce, and expect an initial response within a few days.

## What this project does with your data

- `scripts/jev.py` sends the item text you point it at, plus your questions, to
  `https://api.typesafe.ai/v1/systemone`, or to the gateway set in `TYPESAFE_BASE_URL`.
  That is a third-party service with its own terms and retention policy, so review them
  before sending confidential or personal data.
- The skill instructs the agent to confirm with you before sending confidential or
  personal data for the first time in a conversation, and never to send credentials.
- Your API key is read only from the `TYPESAFE_API_KEY` environment variable. It is never
  written to disk or printed.
- Full answers are written locally to `jev_results.jsonl`, which is git-ignored. Answers
  are labels and numbers, not copies of your text, but they can still reveal information
  about it.

## Prompt injection

Content that the agent investigates, such as web pages and emails, can contain text
written to manipulate AI systems. Jev's answers are limited to the labels and numbers
you define, so they can't carry injected instructions back to the agent. The source text
itself still can, so the playbook includes a screening recipe (recipe 6) to run before
the agent reads untrusted material in full.
