# Materials prompt evaluation

Live evaluations create ordinary chats and saved Summary/Technical Overview
reports in a clearly named validation project. Their materials and citations
come from the running application's public adapters, not expected-answer tables.

## Current checkpoint: public-source diagnostics

Eight short class/application phrases were searched once through the approved
public adapters, with focused-topic matching and a limit of four references per
selected source. All eight registered keyless sources were selected. These were
source-only diagnostics: **no model calls, Goose runs or ranked reports were
produced**. The queries supplied topic hints, not expected material identities.

| Topic phrase                               | References | Audited documents containing specific material mentions |
| ------------------------------------------ | ---------: | ------------------------------------------------------: |
| Halide perovskite photovoltaics            |         21 |                                                       3 |
| Oxide perovskite dielectrics               |         18 |                                                       3 |
| Metal alloy elastic modulus                |         11 |                                                       3 |
| Organic photovoltaic donors acceptors      |         16 |                                                       3 |
| Conjugated polymers optoelectronics        |         11 |                                                       2 |
| Quantum dot light emitting diodes          |         12 |                                                       2 |
| Two dimensional semiconductors electronics |         17 |                                                       3 |
| Metal organic frameworks adsorption        |         16 |                                                       2 |

All eight queries returned references: 122 in total, all retained as approved
discovery documents. The named-document counts are manually audited lower bounds,
not exhaustive extraction or counts of suitable candidates. Twenty-seven sampled
name selections passed exact-source quote validation; two selections containing
HTML subscripts did not. Reference totals include duplicate publication versions,
background pages and papers about neighboring applications. Neither a hit nor a
literal mention establishes a material's class, phase, properties or suitability.

Five arXiv calls were stopped by the adapter's local request-spacing guard because
successive cases completed quickly; this does not establish an upstream outage.
One OpenAlex call reported unavailable or rate limited, without an exposed HTTP
status. The one-pass diagnostic was not retried. The specialized dielectric
corpus deliberately skipped the broad perovskite query because bulk composition
alone cannot establish its requested structure class.

The markup failure prompted a generic abstract-text fix. Allowed inert formatting
now becomes normalized source text: subscript/superscript characters remain
adjacent, paragraph blocks remain separated, and entities are decoded within
bounds. Active, hidden, unsupported and malformed markup is rejected. Instruction
screening runs before formatting removal and again on the complete visible text
before truncation. Quotes bind to the normalized excerpt; response hashes still
bind to the original fetched bytes. This creates no property evidence. The shared
helper also applies to the existing OpenAlex/ChemRxiv abstract path. Ruff and
328 focused regression tests passed. The live counts above precede this fix;
they do not establish post-fix retrieval or model coverage.

## Next live evaluation

The new cross-material Goose matrix awaits sign-in through the application.
At the user's request, seven existing projects were moved to **Removed items**
using recoverable removal. Future actual model evaluations will create fresh,
clearly labeled validation projects with visible chats and saved reports.
The source-only diagnostics above did not create project reports. Repeat the
training matrix with Luna and Sol, then evaluate the unchanged frozen holdout;
do not infer ranked-response success from retrieval counts or regression tests.

## Historical resumed Sol run

The completed reports below were saved in **Materials validation · Sol · September
10**, one of the projects subsequently moved to Removed items. These measured
results precede the discovery-refinement and abstract-normalization fixes.

| Prompt class                                        | Property-backed records | Cited literature leads | Assessment                                                    |
| --------------------------------------------------- | ----------------------: | ---------------------: | ------------------------------------------------------------- |
| Perovskite optoelectronics, target gap 1.78 eV      |                      12 |                      4 | Gap matching works; stability and processing evidence missing |
| Halide perovskite photovoltaics, target gap 1.65 eV |                      12 |                      2 | Gap matching works; processability preference was omitted     |
| Oxide perovskite dielectrics                        |                       0 |                      3 | Names retrieved; no useful dielectric comparison yet          |
| Oxide dielectric screening                          |                      12 |                      6 | Stronger property coverage; stability remains unknown         |
| Nitride optoelectronics, target gap 3.2 eV          |                       0 |                      7 | Names retrieved; target-gap suitability not established       |
| Low-density structural alloys                       |                       0 |                      2 | Broad alloy families only; density preference was omitted     |
| Flexible optoelectronic polymers                    |                       0 |                      0 | Failed: references without candidate names                    |
| Organic photovoltaics                               |                       — |                      — | HTTP error; no completed result                               |
| Quantum dots and adversarial control                |                       — |                      — | Not reached before interruption                               |

All 36 property-backed rows lack thermodynamic, ambient-phase and operational
stability evidence. Mean selected-weight coverage is 24.4%, 29.4% and 65.6% for
the two perovskite cases and oxide case, respectively. A row count alone must
not be interpreted as a validated recommendation or a complete comparison.

Six of the first seven cases passed the original automatic checks. Those checks
verify source linkage, profile class, score reconciliation and nonempty output.
They do **not** prove material specificity, application relevance, adequate
property coverage or stability. Literature mentions remain unscored review
leads, including when they discuss a rejected material or a qualified device.

## Generic corrections prompted by the run

- Retain material-class and application terms in focused public-index queries.
- Permit one bounded discovery refinement and one corrected candidate batch.
  Return immediate exact-source validation feedback, preserve accepted source
  snapshots, enforce source/document/candidate limits and reject ambiguous IDs.
- Preserve explicitly requested low density and solution-processing criteria in
  inferred profiles, while leaving explicit profile choices unchanged.
- Keep compound material scope in attribute searches and associate a passage
  only with the candidate identities literally present in that passage.
- Save evaluation checkpoints after every case and record safe HTTP status
  diagnostics without including response bodies or credentials.

These are implementation changes; their automated regression tests do not
establish improved live scientific coverage. Repeat the training matrix after
deployment, then run the unchanged held-out set with Luna and Sol. Review actual
material identities, application context, measurement methods, conditions,
missing criteria and stability in addition to automatic checks. Report empty,
irrelevant or insufficiently evidenced results as failures; never fill them with
remembered measurements or canned material lists.

The frozen held-out prompt file remains `scripts/holdout_prompts.json`, SHA-256
`9e99c6a5b4746b7817bdb4fdb13ee5660b9eb907a631d6d2bed092a73021adb9`.
Do not tune individual held-out prompts after beginning that evaluation.
