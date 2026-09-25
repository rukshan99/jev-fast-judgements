# Question design and known weak spots

Read this when a question set isn't behaving (the spot-check found errors), or before writing questions for a new kind of judgment.

## The three primitives

| Type | Use for | Required fields | Answer |
|---|---|---|---|
| `noul` | Is it true? | `type`, `instructions`; `criteria` `{true, false}` optional | `noul`: probability of yes, from 0 to 1 |
| `choice` | Which one? (unordered) | `type`, `instructions`, `criteria` as an object `{label: description}` (up to 255 options) | `choice`, `probabilities`, `confidence` |
| `score` | Where on a scale? (ordered) | `type`, `instructions`, `criteria` as an array ordered low to high (2 to 10 levels) | `score` (probability-weighted level number), `probabilities`, `legend`, `confidence` |

Question ids are for the script only and are never shown to the model, so write the full question in `instructions`.

A Noul at 0.5 means "can't tell." It does not mean "medium." If you need a degree, use a Score.

## Structure beats long sentences

`instructions` and `criteria` descriptions can be objects. When two options are easily confused, give each one `what`, `not_for` and `examples`, using the same field names across options:

```json
"criteria": {
  "pricing_question": {
    "what": "Cost, plans, discounts, invoices",
    "not_for": "Whether a feature exists",
    "examples": ["How much is the enterprise tier?"]
  },
  "feature_question": {
    "what": "Whether the product can do something",
    "not_for": "Cost or billing",
    "examples": ["Does it support SSO?"]
  }
}
```

Examples help when they resemble the real inputs; unrelated examples don't. Score levels can be objects too, such as `{"what": "...", "examples": ["..."]}`. When you need to supply a value from code (a record to compare against, or a claim), put it in its own field instead of splicing it into a sentence:

```json
"instructions": {
  "reference_record": {"name": "Acme GmbH", "city": "Berlin"},
  "question": "Does `item` describe the same company as `reference_record`?"
}
```

## Decompose

A broad question hides several judgments inside one number. Compare a single "Is this email phishing?" with a set of atomic checks: asks for credentials, promises an unexpected reward, creates time pressure, sender name conflicts with the domain, link text hides its destination. Ask all of them in one call and combine the results yourself. This is more accurate, and the output shows you why an item was flagged.

For judgments with several factors, ask one Score per factor and weight them in code. Normalize each score by dividing by its top level number first.

## Known weak spots (jev-1.13) and how to work around them

- **Literal reading.** Jev answers the words you wrote, including scoping words and negations. If you catch yourself explaining what you meant, that explanation belongs in the instructions.
- **Arithmetic and counting.** Jev can't count characters, occurrences, or list items reliably, and it can't compare hex colors or numbers. Do the math in code. To count items that match a meaning, ask one Noul per item and sum the results in code.
- **Dates.** Ordering, gaps, and whether a date falls inside a window are all unreliable, especially with mixed formats or relative dates. Extract the date parts (for example, a Choice over months plus `not_stated`), then compare them in code.
- **Indirection.** Double negatives and multi-hop references ("the manager of the person who...") cost accuracy. Point directly at the field instead.
- **Crowded state.** Irrelevant text lowers accuracy. Filter first, if necessary with a cheap Noul per chunk asking whether it's relevant.
- **Scores are not measurements.** A score of 1.4 is not "40% of the way" to the next level. Use scores for thresholds and ranking, not for magnitudes.
- **Adversarial text in the state** can still sway answers. For high-stakes gates, test with hostile inputs and set stricter thresholds.
- **A Choice must pick something.** Without an `other` or `not_stated` option, off-distribution inputs get forced into a wrong label, sometimes with confidence.
- **No generation.** Jev can't write extracted text. Use the pick-from-candidates pattern (playbook recipe 10).

## Choosing thresholds

- Start with keep at 0.5 and treat the band from 0.3 to 0.7 as unsure (the script's defaults).
- For costly false positives (discarding real evidence, merging distinct entities), require 0.85 or higher to act, and review everything else.
- For costly false negatives (missing an injection or an unsupported claim), flag at 0.3 or higher.
- Calibration holds across many items, not for any single item. When a threshold really matters, check a few items yourself and adjust.
