# Projects, chats and pinned contents

The sidebar has **Chat**, **Report Format**, **Search Criterion** and **Connections**. Start a prompt
without a project, or create a project independently. Each project starts with
one **Untitled chat**. The prompt sits directly below the project title, above
pinned reports and resources. It uses an empty starter when available, then
starts another chat for a later question. Each chat belongs to exactly one
project or to **General Chats**. Its header shows that location without an
assignment dropdown.

**Projects** and **General chats** have separate scrolling areas. Click either
heading to give that section more space; click it again to restore your previous
split. Drag the divider between them for a custom split, or double-click it to
return to equal space. With the divider focused, use Up/Down to adjust it,
Home/End for either limit, or Enter to split evenly. The layout is remembered in
this browser, including after hiding the sidebar or clearing a workspace search.

Sidebar titles use at most two wrapped lines, with the full saved title available
on hover. The smaller running-research flask and each item's action menu stay
visible at the default sidebar width. Drag the sidebar's right edge to reveal
more text if desired; this does not change the saved titles.

Drag a chat from **General Chats** onto a project in the sidebar to add it.
The project highlights as a drop target and expands after the move. Its chat
list and counts refresh automatically. Saved messages, reports and sources
remain attached to the conversation, and an open unsent draft stays in place.
For keyboard or touch use, choose **Move chat** from its three-dot menu and
select an existing project, General Chats, or **Create new project**. Creating a
project in this dialog asks for its name and optional description; **Create project
and move chat** completes both steps while keeping the current conversation open.
This also works when no projects exist or when organizing a chat before pinning a
report. A successfully created project is retained if the move cannot be confirmed;
check the saved chat location before retrying, rather than creating another project.
External files, links and text are not accepted as chat moves.

An accepted first prompt gives an untitled chat a concise topic name immediately,
before model or public-source requests begin. The name remains available if
research later fails. Names are derived locally from the prompt without a model
call and serve only as navigation labels, never scientific evidence. Explicit
chat titles are kept.
Previously empty projects receive a starter on startup; existing conversations
are preserved and repeated startup does not duplicate starters.

Every chat also has a permanent workspace number, displayed beside its title as
**#123**. Matching titles remain distinguishable in the sidebar, conversation,
project contents and Removed items. Renaming, moving, removing or restoring a
chat keeps its number. Permanent deletion does not make that number available
for reuse. Existing workspaces receive numbers in creation order without changing
their titles, UUIDs, messages, reports or sources. API responses expose
`chat_number` and `display_title`; `title` remains the editable name and `id`
remains the stable identifier used by API routes.

The three-dot menu beside each project or chat provides Rename and Remove;
chat menus also provide Move chat.
Removal hides the item and its contents from active research context; it keeps
the saved history available through Undo or Removed Items. Restoring a project
also restores its chats except those removed individually. A project whose chats
were deliberately removed does not receive another starter on restart.
The removal dialog can remember **Don't show this again** for recoverable
removal. This preference is stored with the workspace and can be turned back on
in Removed items. The list refreshes after removal and restoration, including
when items are removed from the sidebar while that page is already open.

**Clear all** beside General chats moves all reviewed general chats to Removed
items. It always asks **Are you sure?**, shows the number of chats, and starts
with Cancel focused, regardless of the single-item confirmation preference.
Project chats stay in place; the removed chats can be restored for 30 days.
If the list changes or a general chat is researching, refresh/review the list
and confirm again. A failed request is never retried automatically.

Removed items offers **Restore**, **Permanently delete**, and **Permanently delete all**.
Manual permanent deletion has a separate confirmation and is allowed only for an already removed
item. Deleting a project also deletes its chats and saved reports in the app.
Deleting a chat deletes its history and reports; project-pinned sources and
sources shared with other chats are retained. Permanent deletion cannot be undone
through Removed items and does not erase previously exported files or external backups.
Removed items expire 30 days after removal, with the deletion date shown in the
list. Cleanup runs at startup, every minute while the backend is open, and before
listing or restoring removed items. If the application is closed at the deadline,
cleanup catches up on its next startup. A removed project's remaining contents
expire with it; chats removed earlier keep their earlier deadline. Restoring and
then removing an item starts a new 30-day period. Malformed stored timestamps
are preserved for manual review rather than assigned a guessed deletion date.
Bulk confirmation checks the reviewed list against current storage; if another
window changes it, reload and confirm the new list. It never deletes active items.
New Chat replaces the active prompt view; it does not append another prompt field.

Research continues in the backend when you open another chat or leave its view.
A small bubbling flask marks running chats in both sidebar lists. Returning to a
chat restores its progress; a hidden completion never changes the current view.
Reduced-motion preferences keep the flask still.
The read-only `/api/research-runs` endpoint lists currently running requests for
visible chats so the workspace can recover their activity after navigation or a
page reload. Per-chat `/api/chats/{id}/research-status` supplies phase updates.
Run IDs prevent a duplicate active submission or replay of the most recent run.
These progress records belong to the running backend process; restarting the
backend does not resume unfinished work. Browser navigation is not cancellation.

## Prompt controls

The lower-left controls select **Ranking Profile**, then the language model.
New prompts default to **Infer from prompt**. This uses bounded material-class
and application hints to choose a saved profile or combine catalog priorities for
the requested class and application. Ambiguous hints fall back to the workspace
default. Explicit band-gap targets become ranking preferences, never measurements.
The searchable popup contains all saved profiles,
including presets and custom profiles, with a link to Search Criterion.

An explicit profile applies to the request without activating it globally.
The resulting report records the full profile snapshot and why it was chosen,
so later profile edits do not change historical rankings. A continuing chat
reuses that saved snapshot when its selection is **Infer from prompt** or omitted.
Choose a profile explicitly to change priorities. An explicit new research scope
starts a fresh selection. First requests use inference or the workspace default;
API callers can send `ranking_profile_id: "infer"` or a saved profile ID.

**Find reference structures** starts checked in each new prompt composer. Its
value applies to the submitted prompt; it is not a saved global preference.
Uncheck it to skip the optional reference lookup for that request. For eligible
completed or partial reports, the lookup runs after the report is safely saved,
using selected public structure sources. A failed lookup preserves the report
and its ranked candidates. Structure viewing and explicit retries remain
available from the saved shortlist.

The model popup loads the connected account's available models automatically.
Choose an **Active model** to save the selection and check its connection here;
**Refresh models** reloads the catalog. These checks do not run model inference.
If a check fails after saving, the selection stays saved and **Retry connection
check** verifies it again. New research stays paused until readiness is verified.
Switching models preserves credentials and the existing hosted-call consent
choice. **Connect a model** opens the secure Connections form; available
sign-in methods depend on the Goose provider, including ChatGPT browser sign-in.
Model selection applies to new requests throughout the workspace. **Local
defaults** selects local compute; research still requires a verified model.
Opening either settings panel keeps the chat draft in place. After an uncertain
connection save, reload the saved connection before retrying a change or sending.

Projects expand/collapse their nested chats in the sidebar. Unassigned chats
appear separately. The main project pane contains pinned contents and a prompt,
not a conversations list. A selected chat shows its latest selected Summary and
Technical View, with earlier history still accessible.

Summary keeps the main findings and recommendations concise. Technical View
gives each retained candidate its own heading, cited assessments and evidence
gaps, with one bounded public-source excerpt when available. Separate paragraphs
preserve source phase, sample and measurement
conditions. A short comparison focuses on the first three candidates; numeric
weight, coverage and score contribution details remain in the analysis appendix.
Property records retain their own source identity and do not become literature
recommendations without a validated match. Experimental/computed discrepancies
appear only when the retained observations pass the existing comparison checks;
applicable experimental observations remain the screening basis.
These descriptions are produced from validated saved evidence and assessments,
including when an older report is displayed again. They do not add observations,
change its ranking or turn a tie or missing evidence into a scientific preference.

## Report revisions and pins

Each completed chat turn saves a new report revision containing both Summary and
Technical View. Follow-up prompts refine the active report; earlier revisions
remain in chat history.

**Earlier questions** keeps each previous question, its local date/time and a
compact preview of up to three saved shortlisted materials. The preview retains
the original order, rank ties, scores and caveats. Use the Earlier questions
link in the chat header to jump to that history, then **View saved report** to
open the full revision with its saved format, references and downloads. Original
responses remain available in a separate disclosure. History previews do not
rerun research or replace missing shortlists with another question's results.

New query timestamps record when the server accepted the request; response and
report timestamps record completion. Older records keep their original saved
timestamps. Clarification and declined requests remain in the conversation
without implying that a shortlist was generated.

**Pin options** explains three distinct actions:

- **Pin snapshot** saves the selected revision and its recorded report format.
  Later prompts and changes in Report Format do not update this snapshot.
- **Track latest report** keeps one project pin that follows the chat's newest
  completed report, including reports with explicitly missing data. Blocked
  attempts and clarification questions leave its previous report in place.
- **Update snapshot to latest** explicitly replaces a selected older snapshot
  with the current completed revision. Choose **Pin snapshot** on the new report
  instead to retain both versions in the project. The earlier revision remains
  in chat history in either case.

Project Contents labels snapshots and tracked reports separately. Each pin counts
as one report pair, so a snapshot and a tracked pin can show the same revision
and count as two entries. Source totals count each pinned source once; chat
totals count its report and source pins. Unpinning or stopping tracking preserves
chat history. Removing a chat/project hides both pin modes; restoring it restores
the pins. Moving a chat clears its old project report pins, and permanent deletion
cascades to both modes. Concurrent snapshot replacements reject stale updates
instead of silently overwriting a newer choice.

Research runs save the prompt, reply, report pair, structured ranked candidates,
field-level provenance and source associations in one SQLite transaction.
Discovery sources retain separate versions when their retrieved response or
passages differ, even when they share a paper URL. Each report links to the
version it used. Identical annotations can share a source entry; moving a chat
preserves those version boundaries. Older reports affected by URL-only source
deduplication replay against their own immutable, identity-matched source snapshot.
This recovery is read-only and still requires the normal passage and ranking
validation; a URL match alone cannot establish a scientific claim. Source version
hashes identify stored content and are not signatures authenticating a database.

Property and literature retrieval happen before that transaction. Optional
reference-structure discovery follows the saved report. Moving a chat while research is
running rejects the stale save so results cannot leak into its old project.
Moving preserves history and evidence, clears old report pins and copies or
reuses source links in the destination. Pin moved items again in the new project.

While a request runs, the chat displays elapsed time and actual backend phase
updates: preference selection, safety assessment, public discovery, repository
retrieval, literature review, ranking, formatting, saving and optional reference
structure discovery. Stages may repeat
while a report is refined. There is no simulated percentage or model thought log.
Progress is transient and correlated to one submission; the saved report remains
the durable record. Concurrent submissions in one chat are rejected.

## Context and trust

Model planning prioritizes the active chat's bounded recent messages, latest
completed report and public-source titles, while keeping project pins available
as separate context. Truncation is explicit. User messages, old assistant text,
report titles and pin choices remain untrusted hints. Pins cannot establish facts,
grant permissions or override policy.

For a continuing chat, approved repository identities from its existing sources
can guide a fresh lookup before broader repository discovery. At most six such
identities are considered within the shared 30-second repository budget. Each
lookup must pass the current adapter, public-access and query filters; cached
measurements and report prose are not copied into the new ranking. Failed lookups
are recorded as unavailable, not treated as evidence. Other public references
remain research hints, not automatically validated material-property records.
Cross-project context is not automatic. Large projects need future search and
pagination for exhaustive history selection.

The API exposes chat/project creation, membership changes, pins, contents and
bounded context. It does not expose a source-creation endpoint or accept client
claims of verified provenance. Host, Origin and Fetch Metadata checks protect
the local browser boundary; connection changes also require a session cookie
and CSRF token. This is not multi-user authentication.

## Storage

Docker stores workspace history and saved profiles in the named data volume;
normal stop/restart/recreation retains it. Never remove the volume as a routine
upgrade step. Native Python uses the user's OS application-data directory or
an explicit `LABCAT_DATA_DIR`.

Workspace schema 5 migrates earlier histories transactionally, preserving old
reports and snapshot pins while assigning stable pin identities and adding
tracked pins separately. A supplemental identity table assigns workspace-wide chat
numbers in the same transaction as chat creation; migration covers both active
and removed chats. Foreign keys, full synchronous writes and rollback journaling
protect relationships and interrupted writes. Unknown schemas or corrupt
preferences produce errors rather than resetting history. Conversation storage
is not encrypted by the application; provider credentials use a separate vault.

Back up the SQLite database using its backup API, or copy it while the service
is stopped. Protect backups like conversation history. Do not include credential
vaults, external keys or private workspace data in source or install artifacts.

## Report downloads

Select Summary, Technical View or both with checkboxes. Verbosity remains
concise, standard or detailed; terminology tiers are General overview, Research
context and Specialist detail. TXT, JSON, formatted PDF and Word downloads use
only the saved report, including its citations and caveats. A report's output
checkboxes and format can be changed for downloading without rerunning research.
Ordinary reports and tracked project reports automatically use current
**Report Format** preferences for display and downloads. Pinned snapshots keep
their recorded format. Formatting does not change the saved evidence, rankings,
original report archive or snapshot pins; legacy reports retain their original
prose. If the current format cannot be loaded, the original saved report remains
available with its saved formatting and downloads.

Project sidebar cards show chats, reports and sources on one dot-separated line.
Large totals use compact notation; hover over the counts for exact values, also
provided to assistive technology. Long project names truncate with a full-name
tooltip. The totals still refer to the same saved project contents.
