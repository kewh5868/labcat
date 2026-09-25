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
catalog profiles; this is a screening preference, not evidence of stability.
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
optimum gap or dielectric response. Explicit, active, continued-chat and custom
profiles are preserved. Nothing edits the saved profile, scientific evidence,
source choices, credentials, policy or tool permissions. Candidate identities
and citations can still come only from approved public-source adapters.
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

Offline tests cover independent paraphrases, changes in the roles of the same
words, negation, numeric ambiguity, preservation of user profiles, tampered
scopes and attempts to add evidence or authority fields. These checks validate
the protocol and deterministic preference handling. They do not establish model
accuracy; evaluation across models must separately inspect requested scope and
the relevance of cited results.
