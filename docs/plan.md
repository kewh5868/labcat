# Build plan

## Architecture choice

The project uses scikit-package's lightweight Level 4 layout: a `src/` Python
package, setuptools, tests and CI. Automated public package releases remain
optional. See the [official Level 4 guide](https://scikit-package.github.io/scikit-package/tutorials/tutorial-level-4.html).
Scikit-package provides packaging structure, not an agent runtime.

One constrained Python workflow serves the CLI and the React/TypeScript
application through FastAPI. Vite compiles the interface into the same Docker
image. Native Tauri, browser and headless modes share that backend. The Docker
image embeds pinned Goose with a closed intake decision and two research tools.
The workspace runs locally; new research requires a verified model connection.

## Implemented milestones and remaining gates

| Area                       | Current implementation                                                                                                                               | Remaining verification or extension                                                                      |
| -------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| Foundation and deployment  | Python package, strict configuration, React/FastAPI, two container architectures, native shell and host launchers                                    | Target-host installation coverage; signing/notarization for native distribution                          |
| Research workspace         | Standalone/project chats, history, saved reports, source links, pins and Project Contents                                                            | Broader multi-user operation requires authentication and roles                                           |
| Public scientific search   | Selected repositories, targeted open-access passages for missing attributes, normalized evidence, deterministic ranking and cited reports            | Broader verified fields and source coverage; literature leads remain unscored                            |
| Ranking profiles           | Class/application presets, custom profiles, grouped attributes, independent importance and automatic normalization                                   | Unsupported attributes remain explicitly unscored; adding a profile does not implement a new utility     |
| Model planning             | Embedded Goose with mandatory suitability assessment and two fixed research tools; supported account/model connections and actual plan/usage records | Live account checks are listed separately in validation; Claude subscription login remains unimplemented |
| Onboarding and credentials | Required model verification, optional cloud/data connections, saved nonsecret profiles, session keys and encrypted vault controls                    | Site-managed secret injection and account setup remain deployment responsibilities                       |
| Report presentation        | Written Summary and full Technical View, selected outputs, verbosity and terminology; TXT/JSON/PDF/Word downloads                                    | Target-host document-reader compatibility; exact checks are in the validation record                     |
| Developer settings         | Explicit developer edition, bounded stage/history controls, search budgets and default model connection; absent user-edition API                     | Multi-user authentication, policy drafts, evaluation comparison, activation and rollback remain planned  |
| Shared cloud hosting       | Bedrock can perform optional inference through an authorized AWS profile                                                                             | Hosting the whole service on ECS Fargate remains planned; no automatic provisioning                      |

Container checks exercise conflict-free startup, read-only/non-root hardening,
offline research, source/report pins, profile persistence, project isolation,
connection CSRF and encrypted vault behavior across replacement. Exact builds,
checks and remaining platform limits belong in [the validation record](validation.md).
An earlier passing image is not evidence that a later source change was tested.

## Scientific scope

Selected public repositories are searched before missing-attribute follow-up in
available open-access article text. Optional database connections add quantitative
coverage; the catalog is source-neutral. New installations enable public discovery
by default; saved filters remain
respected. Requests may concern any material class, although quantitative coverage
varies. No production search substitutes a stored cohort or predetermined output.
Offline runs return explicit evidence gaps. Additional sources require reviewed
adapters; an API key does not authorize private or paywalled access.

Only source adapters create material facts. User text, pasted values/citations,
model memory and prior reports cannot fill an evidence field. Models receive
bounded untrusted prompt/project context. Goose must assess suitability before its
two empty-argument research tools can execute. Models cannot select destinations,
generate evidence or relax policy. Unclear and refused turns create conversation
messages without reports, sources or scored candidates.
Rendering uses source-backed fields and labeled deterministic derivations.
Literature passages retain attribution and remain unscored until their material
identity, units and conditions can be verified.

Missing stability, compound safety and application-performance evidence stay
unknown. Scores disclose component utilities, contributions, normalization and
tie-breaking; they express preferences, not calibrated scientific truth. Element
screening cannot certify non-toxicity. Bulk dielectric values do not qualify a film.

## Configurable research preferences

Scientists can select a preset or save a custom material-class/application
profile. Each curated attribute has an independent importance from zero to one;
values need not total one. The ranker normalizes across the selected criteria,
including unsupported criteria whose contributions remain zero. The UI labels
available scoring and missing coverage. A custom label is context, not a promise
that the source covers that material class.

The broader class catalog includes exploratory labels for polymers, perovskites
and perovskitoids, ceramic oxides, metals/alloys, metal-organic frameworks,
high-entropy alloys, quantum dots, polymer- and ceramic-matrix composites,
biomaterials, elastomers, liquid crystals, thermosets and thermoplastics. These
are preference templates, not datasets or material-property claims. Live discovery
can follow these research questions; each adapter still has limited coverage.
Additional verified fields and scoring utilities require implementation and review.
These new templates initially weight evidence coverage and element screening;
their material-property importance starts at zero for the scientist to set.

The existing five-weight TOML interface remains available for the CLI
and still requires a sum of one. Previously saved web weights migrate into a
custom profile when needed. Web profile changes apply to new reports and do not
rewrite historical results.

Search Criterion shows the active ranking profile above the editing preview.
Report Format owns document previews and appearance, with layout preferences
snapshotted into new reports. Presentation controls select Summary,
technical/audit output, or both;
concise/standard/detailed verbosity; general/research/specialist terminology;
and TXT/JSON/PDF/Word formats. Exports preserve citations and caveats from the
saved report without recomputing facts with a language model.

## Connection and deployment boundaries

The default performs local deterministic work. Optional Ollama requires a local
runtime and downloaded model; no model weights ship in the application image.
Hosted adapters require supported API credentials or an AWS profile plus explicit
cost/data consent. Consumer chat subscriptions are not universal application
logins. Model-list and AWS identity checks do not establish inference permission,
available quota or structured-output compatibility, and do not invoke a model.

Nonsecret profiles persist. Credentials are session-only unless the scientist
chooses an encrypted vault. Passphrase vaults restart locked; deployment-provided
keys can support automatic unlock. No key/passphrase enters ordinary config,
SQLite or browser storage. “Use local defaults” disables the model provider but
retains a configured Materials Project key; it is a compute choice, not an offline
switch. There is no silent paid fallback.

Keep this version single-user and local. Host/Origin validation and connection
CSRF checks do not replace authentication. Shared cloud hosting and the
[developer console](developer-mode.md) need explicit identity/role enforcement.
Use the versioned image archive and host launchers described in
[deployment](deployment.md); end users should not need a source build.

## Future work

1. Expand verified scientific coverage through reviewed public adapters,
   class-specific eligibility and documented scoring utilities. A broader class
   menu alone does not implement these capabilities.
2. Validate live Materials Project and optional model connections with authorized
   site accounts. Measure retrieval coverage, model behavior and failure paths;
   mocked protocols and metadata checks do not prove inference access.
3. Install the exact release artifacts on Windows and native Linux hosts, and
   test browser/native downloads with their document readers. Complete native
   signing/notarization and site release checks before broad distribution.
4. Add an authenticated developer console with explicit roles, read-only evidence
   inspection, validated policy drafts, regression comparisons and rollback.
5. Design shared/cloud hosting with identity, authorization, deployment-managed
   secrets and operational controls. Optional Bedrock inference does not host
   the application or provision an AWS deployment.

Keep image smoke tests, distribution privacy checks and normal/adversarial
evaluations as release gates for every source change. The design note, README
and evaluation examples describe this prototype; the
[validation record](validation.md) identifies the tested artifacts and limits.
