# Frozen materials holdout

The holdout is `scripts/holdout_prompts.json`, schema `materials-holdout-v1`.
It contains ten new prompts spanning halide and oxide perovskites, elemental
metals, alloys, organic photovoltaic donors and acceptors, quantum dots, polymer
barrier coatings, polymer electrolytes, and an unrelated-request control.

Frozen on September 10, 2026, at 23:09 UTC, before running these cases against
the candidate-lead implementation. The exact UTF-8 file is 8,839 bytes and has
SHA-256:

```text
9e99c6a5b4746b7817bdb4fdb13ee5660b9eb907a631d6d2bed092a73021adb9
```

Do not edit prompts, scope labels or rubrics after observing runs. Verify this
hash before evaluating; a mismatch invalidates comparison with this frozen set.
If requirements later need a different holdout, create a separately named and
versioned file rather than replacing this one.

## Evaluation rules

The file fixes questions and behavior/evidence rubrics, not expected materials,
measured values or candidate counts. A useful source-grounded lead can pass the
discovery criterion even when quantitative comparison is unavailable, provided
its identity and supporting quotation are traceable and its missing measurements
and unverified suitability are explicit. A merely plausible material name or an
unrelated cited paper cannot pass.

Evaluate discovery usefulness separately from scientific claim correctness,
source linkage, scope preservation, presentation and refusal behavior. Record
actual response, source availability and elapsed time without replacing a failed
or empty result with a canned answer. Distinguish a transport failure from an
unsupported material class and from a safely empty evidence result.

Results are held-out evaluation evidence. Once seen, these exact cases must not
become the basis for implementation tuning followed by a claim of unseen
performance. New development checks should use separate prompts; later evaluation
requires a newly frozen set. No live run was performed while creating this file.

## Candidate-lead presentation boundary

Keep candidate leads separate from scored quantitative candidates. Summary should
give a short account of what was actually found and a compact review table;
Technical View should preserve the complete lead list, supporting quotations and
all evidence gaps. Names should link to the approved source record, with the
source title visible. Label the ordering as review order, avoid score colors and
performance badges, and say that cited mention does not establish suitability,
stability or a measured property.

The report generator in `science/reporting.py` should provide the same written
content to saved reports and document exports. Frontend presentation should add a
separate validated lead table rather than extending the quantitative score-table
schema. Historical reports without candidate-lead metadata should retain their
existing presentation.
