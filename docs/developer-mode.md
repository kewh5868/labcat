# Developer edition and research controls

The normal installation is the **user edition**. It includes Chat, Report Format,
Search Criterion and Connections. The same image can start in an explicit
**developer edition**, which adds Developer Settings below Connections. A browser
query, prompt, request body or hidden button cannot enable its backend routes.

## Start the developer edition

For a local source checkout on macOS or Linux:

```sh
LABCAT_EDITION=developer ./labcat.sh start --no-open
```

On Windows PowerShell:

```powershell
$env:LABCAT_EDITION = 'developer'
.\labcat.ps1 start -NoOpen
```

Open the loopback URL printed by the launcher in a browser. To use the native
shell, launch it with `--url` and that exact URL. A standard desktop-icon launch
uses the default user edition unless its process environment explicitly enables
the developer edition. To return to the normal edition, set
`LABCAT_EDITION=user` and restart with the same launcher. Research history,
profiles and installed developer defaults remain in the same workspace.

This is a single-user deployment mode, not a multi-user administrator login.
Anyone with local access to a deliberately enabled developer instance can change
these controls. Keep its existing loopback binding. Shared/cloud installations
need identity and authorization before offering administrative access.

## Controls available now

Developer Settings saves nonsecret configuration transactionally and applies it
to future research. Each new result records its effective controls; current runs
and historical reports retain their settings. Direct CLI research with
`--connections` reads that workspace’s installed controls and source selections;
corrupt saved controls stop research instead of silently resetting the limits.

| Control                               | Effect                                                                                                                             |
| ------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| Public reference search               | Allow or suppress searches within the scientist's selected services                                                                |
| Missing-property literature follow-up | Allow or suppress bounded open-access article searches                                                                             |
| Preprint references                   | Disable arXiv/ChemRxiv and exclude preprint or unconfirmed publication types in OpenAlex/Europe PMC searches and article follow-up |
| Project history                       | Include or omit bounded, untrusted project context sent to the model                                                               |
| Search budgets                        | Lower reference counts, attribute queries, article requests, elapsed-time and agent-call caps                                      |
| Default model connection              | Use a saved account only when no account is selected; authentication, selected model and inference consent remain required         |
| Interactive structure viewer          | Enable or disable JSmol structure display; turning it off keeps supported structure downloads available                            |

Developer settings can narrow research choices; they cannot activate an unselected
source or introduce a new host or tool. User prompts, model memory and retrieved
instructions never establish scientific facts. Private data, paywalls, wetlab
actions, arbitrary shells, host-file access and invented citations remain
unavailable. These boundaries are displayed for inspection and are not switches.
Changing adapters or evidence policy requires reviewed source changes and tests.

The user edition applies saved installation controls but exposes neither the
Developer Settings tab nor its GET/PUT API. Developer writes require the same
local session, Host/Origin validation and CSRF protection as credential/settings
writes. No browser state can substitute for server startup enablement.

The structure viewer is enabled by default. Existing saved controls that predate
this option gain only `viewer_enabled: true` when loaded; all prior research
limits and the saved model selection remain unchanged. An explicitly saved
`false` survives restart and also applies in the user edition. Settings writes
require a boolean and the complete supported control set; malformed saved values
do not silently reset the installation to defaults.

Unlike a research result's historical control snapshot, interactive viewing uses
the current installation switch when a structure view is opened. Disabling it
prevents new viewer frames and JSmol loads while keeping structure download links.
Scientists can read viewer availability in a report's structure information, but
the user edition provides no API for changing the installation switch. Closing
an already opened viewer releases that view; changing the switch cannot revoke
structure data that a user has already downloaded.

## Scientist-facing configuration

**Search Criterion** edits and saves ranking profiles. Importance values range
independently from zero to one and are normalized by the backend. The active
profile appears above the editing preview. New attributes start at 0.5; saved
weights stay unchanged. Unsupported attributes retain their weight and contribute
zero with an explicit missing-coverage indication.

This section also selects sources and public reference filters. Credentialed
APIs are selectable only after a successful current connection test. Changed,
locked, forgotten or failed credentials invalidate readiness. Automatic source
selection may use another enabled public repository; requiring an unverified
API fails with a connection explanation. Keyless public services remain usable.

**Connections** owns compute, model accounts, provider/model selection, public
API credentials and the data registry. Keys are write-only and stay in memory
or the optional encrypted vault outside the repository. No connection grants
access to private science or changes the evidence policy.

**Report Format** owns Summary/Technical View selection, verbosity,
terminology, download format and appearance. PDF/Word support Letter/A4, sans/serif,
font size, spacing, accent, table style and page numbers. TXT supports wrapping
width; JSON supports indentation. Template previews have placeholders and never
pretend to contain research results. Preview downloads use the same renderer as
saved reports. Word pagination can vary with the reader and installed fonts.

New reports record their presentation and layout. Ordinary reports and tracked
project reports automatically use current Report Format preferences for display
and downloads; pinned snapshots retain their recorded format. Historical reports
without layout metadata use current layout preferences. Legacy prose, saved
evidence, rankings and the original report archive remain unchanged. Formatting
and report previews require no model call, generate no scientific evidence and
create no chat.

## Remaining work

The prototype does not implement multi-user roles, policy drafts with activation
and rollback, general scientific claim extraction, or an interactive evaluation
console. Broader source adapters and scoring utilities require separate review.
The bounded settings interface is not a guarantee of prompt-injection immunity;
capability isolation and evidence validation remain the principal controls.
