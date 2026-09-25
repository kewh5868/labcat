# Research intake and evidence safeguards

Every request receives a server-owned intake decision before research retrieval.
Explicit requests for private or paywalled data, invented evidence, wetlab actions,
or selection/manufacture/improvement of materials for weapons or harming people
are refused. Checks combine enabling intent with harmful targets; isolated terms
such as ballistic transport, catalyst poisoning or explosive crystal growth do
not establish harmful intent. Detection, protection against a threat, disposal
and remediation exceptions apply to the specific target being discussed. A
benign safety phrase does not authorize a second harmful target in the same
request. Explicit intent to poison or injure people is also refused without
requiring a weapon name. Fictional scenarios and claimed administrator/PI
authority do not grant an exception.

Line breaks, bounded HTML entity escapes, compatibility characters and hidden
formatting do not remove the fixed intake check. Requests to reveal credentials,
access tokens or environment variables are refused before contacting a provider.
These bounded text checks provide basic resistance, not comprehensive intent
understanding; they are not a claim of multilingual or universal jailbreak
resistance. The model may narrow accepted scope further, never widen it.

Vague requests and requests outside the recognized materials scope receive three
guiding questions about the material/property, application and priorities. New
research still requires the configured verified language-model connection;
clarification does not bypass that setup requirement. Fixed refusals happen before
contacting a provider. Fixed-intake clarification does not call the research model.
A connected model may also request clarification after its intent assessment;
neither path retrieves scientific sources. Messages remain in their chat without a report,
candidate, source, ranking or pin-able report artifact.

Direct model planning returns closed preference enums. An unsupported decision
requests clarification instead of searching references. Goose must first call
`assess_research_intent` with a closed decision. Only a server-accepted request
and a `materials_research` decision permit its two empty-argument retrieval/report
tools. The model cannot approve a server refusal, change its decision mid-run,
supply its own tools or evidence, or replace reports with prose. Omitting intake
does not authorize the server to retrieve on the model's behalf.

Follow-up intake uses bounded user preferences from the same chat only. Stored
refusal state and a full original-message boundary check preserve harmful intent
that would otherwise be lost by text truncation. A short continuation cannot clear
that context. A concrete benign new materials question can establish a new scope.
Other project chats, assistant prose and pinned reports/sources never establish
intake facts or authority. History can be disabled by deployment controls.

Only approved public-source adapters create evidence. Metadata titles and article
passages are screened for instructions, including again at the persistence
boundary. Text, citations, measurements and numerical claims supplied by users or
models cannot become property records. Prompt thresholds are preferences, not
automatically enforced acceptance limits; saved ranking profiles own the weights
and scoring rules. Unknown properties remain unknown. Profiles and execution
settings are saved with completed research for traceability.

Tests cover normal materials scope, benign ambiguous terminology, harmful
manufacture and negation bypasses, vague/off-topic clarification, missing/model
rejected intake, same-chat continuation, no-report persistence and source-instruction
rejection. Synthetic provider/adapter fixtures are test-only; these checks make no
scientific claims and use no personal provider credentials.

Safety regression cases must exercise both the original wording and an ordinary
material-class or same-chat context variant. A dangerous request that merely
receives clarification has not passed a refusal check: adding a class can remove
that clarification without removing the unsafe purpose. Test the server decision
and the research-tool session before allowing any provider or source call.
Keep the original failed outcomes when evaluating a repair. Include paired benign
controls for public research, protective equipment, detection, and explicitly
negated private-access or disclosure actions.

`tests/test_research_adversarial.py` adds high-level harmful-intent paraphrases,
authority spoofing, credential-exfiltration requests, line-wrapped private-source
requests and retrieved role-tag instructions. It explicitly tests a model
incorrectly approving a server-refused request, as well as benign safety and
materials-language controls. Existing source/structure transport tests separately
check fixed routes, rejected private DNS results, redirects, byte limits and
source-only provenance. Re-run these offline gates after changes, and run live
scientific usefulness checks separately: an unsafe request should be refused,
not receive a shortlist merely to satisfy a nonempty-output metric.
