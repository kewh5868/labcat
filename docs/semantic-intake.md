# Semantic request intake

Goose may classify a request using `semantic-intake-v1` before research starts.
The interpretation separates the material being sought from its application,
environment and processing conditions. Material class and application are closed
catalog choices; the server also accepts an explicit unknown class/application.
Identity scope is bulk, molecular, nanoscale or unspecified. These are search
preferences, not classifications of retrieved materials as scientific facts.

Role snippets must be exact, bounded substrings of the original request. The
server derives the target search text from one to three target snippets. Context
snippets cannot contain or be contained by target snippets. Negated subjects,
source claims, URLs, instructions and hidden controls are rejected. Other
validation checks the schema, catalog identifiers, list lengths, duplicate
criteria and total payload size. A validated interpretation remains fallible:
literal binding proves where a request phrase came from, not that the model
understood its meaning correctly.

The intake schema supplies each criterion's current label and description from
the shared catalog, including the distinction between thermodynamic, phase and
operational stability. Its instructions ask the model to review the requested
use and retained processing/environment spans for all corresponding preferences.
Context alone does not create a goal, and a missing catalog match must not be
replaced with an invented proxy. These are interpretation aids, not automatic
phrase rewrites or proof of semantic correctness. The accepted argument shape,
tool-call budget and preference authority are unchanged.

Goals contain a catalog property identifier, an exact request snippet, one of
three priorities, and a relation: consider, maximize, minimize or target. Relations
refer to the catalog concept: maximizing thermodynamic stability corresponds to
lower hull energy, while maximizing composition simplicity corresponds to fewer
elements. Newly added priorities use fixed importance values:
primary 1.0, normal 0.5 and secondary 0.25. Existing stronger catalog priorities
remain in place. The three stability criteria remain at least 0.3 in generated
class-specific
catalog profiles; the neutral baseline uses only supported-field completeness.
These are screening preferences, not evidence of stability or performance.
Numeric band-gap goals use the existing whole-request preference parser. A model
cannot supply a numeric property, invent a target value or select one target
while hiding another contradictory target elsewhere in the request.

The server identifies selected goals unsupported by the existing utility.
For example, the current density utility favors lower density; it does not
implement a request for higher density. Inferred profiles retain such goals as
selected but unscored review requirements. An explicit profile remains
authoritative and the mismatch is disclosed. Numerical targets are supported
only where the server can parse the literal goal and match it to the actual
profile's utility (currently band-gap targets); other requested targets remain
unscored. Legacy goal payloads without a relation mean consider.

Automatic or fallback selections can receive a new per-run catalog profile.
An unknown application uses property exploration, avoiding assumptions about an
optimum gap or dielectric response. Explicitly selected and active profiles
retain their saved ranking criteria. Automatic selection reassesses each
question with bounded same-chat user context rather than protecting the previous
report's inferred weights as a manual choice. Nothing edits the saved profile,
scientific evidence, source choices, credentials, policy or tool permissions.
Candidate identities and citations can still come only from approved public-source
adapters.
An unresolved material class uses a neutral custom/property-exploration profile
and remains explicitly unknown in the search scope; it does not inherit the
previous oxide profile's property weights or screening threshold.

The assessment schema is shared by the parent and both Goose transport
boundaries. Decision-only legacy assessments remain valid and do not acquire a
semantic scope. The parent binds snippets to its original request and the source
boundary revalidates the resulting scope. New report metadata records the intake
version and literal preference provenance; older saved reports and pins are not
reinterpreted, and no workspace database migration is needed. Backend and worker
must use the same tool catalog when the expanded contract is deployed.

## Clarification and model recovery

A valid research question does not need to fit every catalog application or
property. For a stated application outside the catalog, the model can select
`custom`; an unstated application uses `unknown`. Unmapped physical properties,
selectivity and competing-reaction constraints remain literal request context.
They do not become invented catalog criteria, proxy measurements or scored data.

If a full semantic interpretation cannot be expressed, the model may submit the
existing decision-only assessment. That minimal assessment permits research only
when the server's original scope check already accepted the question. It cannot
promote unresolved scope, bypass a refusal or replace a previously frozen model
decision. Rejected intake arguments receive fixed repair guidance at both worker
and parent boundaries without reflecting their contents. Corrections use the
same tool-call and time budgets; there is no extra model retry or unrestricted
fallback tool.

An incomplete model assessment is shown as **Research not started**, with an
explanation to retry or select another model. It no longer asks the user for
material, application and constraints that may already have been supplied.
Actual clarification requests and safety refusals retain their separate messages.
Saved historical replies are not rewritten.

When a saved request is awaiting clarification or model assessment, a follow-up
can retain bounded earlier user preferences from that same chat even if its new
material-class phrase passes the scope check by itself. When a literal target or
goal span appears in the current turn, its current context takes precedence over
an older matching exclusion. The server records that turn boundary independently
of model arguments and any user-written labels. Conflicting numerical goals
remain unscored until clarified; the model cannot choose one by omitting another.
Explicit new-topic resets and disabled history still apply. Assistant prose never
supplies material preferences, and refused context cannot authorize retrieval.
These are continuity hints, not scientific evidence.

Offline tests cover independent paraphrases, changes in the roles of the same
words, negation, numeric ambiguity, preservation of user profiles, tampered
scopes and attempts to add evidence or authority fields. These checks validate
the protocol and deterministic preference handling. They do not establish model
accuracy; evaluation across models must separately inspect requested scope and
the relevance of cited results.
