# Materials prompt matrix

`scripts/materials_prompt_matrix.json` is a development evaluation fixture, not
application answer data. It contains **72 requests** and is **not yet executed**.
Preparing the fixture and running the evaluation command in dry-run mode does
not demonstrate that any model returned useful materials.

The fixture covers all 20 noncustom material classes in the current catalog,
with three requests per class: a direct class-name request, an implicit family
description, and a constraint or tradeoff. Most requests use everyday language.
One perovskite description deliberately uses technical structural terminology
and is tagged accordingly. Twelve additional cases exercise spelling mistakes,
negation, contextual roles, mixed and custom families, insufficient information,
contradictory preferences, impossible requirements, unrelated requests and an
unsafe instruction.

This is an inspectable development matrix. It does not replace an independently
prepared unseen holdout. Candidate names, measurements and a desired output
order are never supplied as expected answers, and the application must not
contain responses tailored to these prompts.

## Coverage

| Catalog family               | Direct | Implicit | Tradeoff |
| ---------------------------- | -----: | -------: | -------: |
| Oxide dielectrics            |      1 |        1 |        1 |
| Structural ceramics          |      1 |        1 |        1 |
| Semiconductors               |      1 |        1 |        1 |
| Polymers                     |      1 |        1 |        1 |
| Perovskites                  |      1 |        1 |        1 |
| Perovskitoids                |      1 |        1 |        1 |
| Ceramic oxides               |      1 |        1 |        1 |
| Metals and metal alloys      |      1 |        1 |        1 |
| Metal-organic frameworks     |      1 |        1 |        1 |
| High-entropy alloys          |      1 |        1 |        1 |
| Semiconductor nanocrystals   |      1 |        1 |        1 |
| Organic electronic materials |      1 |        1 |        1 |
| Two-dimensional materials    |      1 |        1 |        1 |
| Polymer matrix composites    |      1 |        1 |        1 |
| Ceramic matrix composites    |      1 |        1 |        1 |
| Biomaterials                 |      1 |        1 |        1 |
| Elastomers                   |      1 |        1 |        1 |
| Liquid crystals              |      1 |        1 |        1 |
| Thermosets                   |      1 |        1 |        1 |
| Thermoplastics               |      1 |        1 |        1 |

There are 60 catalog-family cases and 12 edge cases. Of the 72 requests, 67
expect research and five expect clarification or a scope/safety response.
Each broad research case requires at least three usable ranked candidates;
the five control cases require no candidate generation. Five requests include
numerical band-gap targets, all explicitly recorded as preferences in the test
metadata.

## Schema and acceptance

The top-level schema identifier is `materials-prompt-matrix-v1`. The evaluation
runner reads the `cases` mapping using `--prompt-set`.

Each case contains:

- `prompt`: the user request sent to the application.
- `class` or `accepted_classes`: the expected catalog family or acceptable
  interpretations of an ambiguous/custom request. These are assertions for the
  evaluator, not instructions sent to the research model.
- `candidates_expected` and `minimum_ranked_candidates`: whether a useful
  shortlist is expected and the minimum usable ranked count.
- `decision_criteria`: catalog criteria relevant to the requested decision.
  Generic record completeness, composition simplicity, element screening or
  site count alone must not qualify a row as a useful application comparison.
- `expectation`: a case-specific behavior rubric for human review.
- `family`, `variant` and `tags`: test organization only.
- Optional `expected_goals`: selected criteria and their requested directions,
  using `consider`, `maximize`, `minimize` or `target`.
- Optional `target`: the requested band-gap value, never a material measurement.
- Optional `expected_role_spans` and `forbidden_target_spans`: limited literal
  snippets for target/environment/processing checks. Matching allows a larger
  correctly identified span to contain a snippet rather than requiring exact
  model segmentation.
- For controls, `control` and `expected_intake_statuses`: acceptable
  clarification/refusal outcomes. The unsafe case additionally sets `refusal`.

A nonempty paper list or an unevaluated material mention is insufficient for a
research-case pass. Report useful numerical shortlist rows and genuinely
evaluated provisional literature rows separately from raw table length, cited
lead count and reference count. A provisional fit must remain an interpretation
of source passages with visible criterion assessments, coverage and uncertainty;
it is not a verified material measurement.

For each class, inspect all three variants. A direct keyword match succeeding
while the ordinary description fails does not establish reliable inference.
Likewise, naming the correct class is insufficient if the ranking ignores the
requested direction, confuses a solvent with a candidate, or silently chooses
one side of a mixed-family comparison.

The catalog currently lacks several application-defining criteria, including
adsorption capacity, emission intensity, toughness, electrical conductivity and
biological compatibility. Some cases therefore have stability as their only
machine-checkable decision criterion. Passing that check does **not** establish
that the answer addresses the main application. Review the full expectation
and actual report for these properties, useful candidate identity, applicability
and a clear statement of unsupported comparisons. Do not call an automated
coverage pass a scientific success.

Stability must be assessed in its relevant scope: thermodynamic stability,
room-temperature phase persistence and durability during operation are distinct.
When both experimental and computed information is available, recommendations
should prefer applicable experimental observations while retaining discrepancies
and incompatible conditions. Structure checks apply where an approved source
actually offers a supported file; an unavailable or unverified structure must not
be invented to pass a case.

## Running the matrix

Dry-run inspection makes no application or model requests:

```sh
.venv/bin/python scripts/evaluate_live_prompts.py \
  --prompt-set scripts/materials_prompt_matrix.json
```

For live evaluation, first finish the intended application changes, record the
code/image version, and use the active main application's current local address.
The user must already have completed any required provider sign-in. Choose and
verify a model through the application's normal model settings; the script has
no model-selection flag and uses the currently selected connection.

Run into a fresh, clearly labeled project and a new private result file. Replace
the example address and model label before running:

```sh
LABCAT_MATRIX_SERVER='http://127.0.0.1:PORT'
test ! -e .local/current-ui-review/materials-matrix-MODEL-20260911.json && \
  .venv/bin/python scripts/evaluate_live_prompts.py \
    --server "$LABCAT_MATRIX_SERVER" \
    --prompt-set scripts/materials_prompt_matrix.json \
    --project-name 'Materials matrix · MODEL · 2026-09-11' \
    --output .local/current-ui-review/materials-matrix-MODEL-20260911.json \
    --run
```

The full matrix can create 72 fresh chats and consume the active provider's
usage. To inspect one family first, repeat `--case` for its three identifiers,
such as `polymers__explicit`, `polymers__implicit` and `polymers__tradeoff`.
Keep subset results separate from the full matrix and state which cases ran.

Repeat the unchanged matrix with each selected model in a separate project and
result file. Record the actual provider/model returned by the application, not
merely the project label. Do not modify implementation between paired runs in
response to individual results. Preserve partial failures and record retries
separately. Continue through individual resource outages, but count genuinely
insufficient evidence as a coverage failure rather than supplying canned output.

## Freeze record

The exact JSON fixture was frozen on 2026-09-11 with SHA256:

```text
8e50b3d221f2f5a5a8bea3b653a00428d927a2a8fb1b7ffcaedee45197991dd3
```

Verify before a paired run:

```sh
shasum -a 256 scripts/materials_prompt_matrix.json
```

Offline checks verified all 20 catalog families have exactly the three required
variants, 72 unique prompts, valid criterion IDs, explicit minimum counts,
numerical metadata for all target goals, and literal role snippets present in
their corresponding prompts. The runner accepted the file in dry-run mode.
No live inference, retrieval, candidate quality or model comparison is claimed
by those checks. Changes after the first live run require a new fixture version
and hash; retain the earlier fixture/results for comparison. Existing frozen
holdouts remain separate and unchanged.
