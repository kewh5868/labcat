# Using Labcat

Labcat explores materials through public sources and saves cited shortlists,
property records, chats and reports. Compatible public records can also supply
structures to view and download. Coverage and answer quality vary by topic;
results are provisional screening aids, not predictions of material performance.

Start with the [first-run walkthrough](first-run.md) for exact installation
commands and setup clicks, then try the [example research prompts](examples.md).
For installation alternatives, see [installation](installation.md); for account
recovery, see [model setup](onboarding.md).

## Start a research chat

1. Choose **New chat**, or **Create project** to group related work. A new project
   starts with an untitled chat; write your question beneath the project title.
2. Describe the material class, its role, and your preferred properties and
   operating conditions. Ask for missing evidence explicitly.
3. Check the controls below the prompt. **Infer from prompt** selects ranking
   preferences from the supported catalog; choose a saved profile explicitly
   when you want its exact priorities. The model control selects the connected
   model. **Find reference structures** enables an optional lookup after the
   report is saved.
4. Submit the prompt. Labcat shows elapsed time and research stages. An unclear
   request may receive a clarification question instead of a report.
5. Review **Summary**, **Technical View** and **Sources**, then ask a follow-up
   in the same chat. Each completed report is saved as a new revision.

A flask marks a running chat. You can open another chat or reload the page and
return to its progress. Stopping or restarting the backend interrupts unfinished
work; it does not resume automatically.

## Connect or change a model

Open **Connections** to sign in to ChatGPT or configure a supported API provider,
select a model and consent to sending research context. **Save and test
connections** checks readiness without running inference. Research uses the
provider's allowance or billing; local workspace processing still needs a model.

The model popup beneath a prompt can change models or open Connections while
preserving your draft. Changes apply to new requests throughout the workspace.
Credentials are session-only by default; optional vault storage can retain them
and may need unlocking after restart. Chats and reports persist independently.
See [connection setup and recovery](onboarding.md).

## Organize and revisit work

Select a project for its pinned contents or expand it to open a chat. Permanent
chat numbers distinguish conversations with matching names.

- **Earlier questions** opens the chat's prior questions and report previews.
  Choose **View saved report** to inspect a revision and its downloads without
  rerunning research.
- Drag a General Chat onto a project, or choose **Move chat** from its three-dot
  menu. Moving preserves history but clears report pins in the old project;
  pin the reports again in their new location.
- **Pin snapshot** preserves one report revision and its recorded format.
  **Track latest report** keeps a project pin following the chat's latest
  completed report. **Update snapshot to latest** explicitly replaces an older
  snapshot; pin a second snapshot if you want both versions.
- **Search workspace** finds project names and descriptions, chat titles, and
  saved message or report text. Search runs locally without a model call.
  Select a result to open it; clear the search or press Escape to return to the
  sidebar lists.
- **Remove** moves a chat or project to **Removed items**, where it can be
  restored for 30 days. Permanent deletion and expiry remove it from the app.
  Exported files and external backups are separate.

The Projects and General Chats lists scroll independently; drag their divider
to resize them. See [projects, history and pins](projects.md).

## Choose criteria and change their influence

**Search Criterion** contains ranking profiles, material/application presets,
attributes and public-source choices. Presets express preferences; they do not
expand evidence coverage. Materials Project requires a verified API key; the
other supported sources do not require keys in Labcat.

To try different priorities:

1. Choose **New ranking profile**, give it a name, and select the relevant
   attributes or preset.
2. Adjust each importance from **0 to 1**, using its slider or number field.
   Values are independent and do not need to add to one; Labcat calculates their
   relative weights. Keep at least one positive importance.
3. Choose **Save ranking profile**. **Use ranking profile** makes it the workspace
   default.
4. Select that named profile in the prompt's ranking control and submit a new
   request. Check the resulting report's recorded profile and weights.

An explicit selection applies to that request without changing the workspace
default. **Infer from prompt** may choose other catalog priorities; continuing
a chat normally retains its previous profile, with new goals able to refine
inferred preferences. Always check the report's recorded selection.

Higher relative importance gives an attribute more influence when usable
assessment or property evidence exists. It cannot create missing evidence, and
candidates may remain tied. In the separate property calculation, missing or
unsupported criteria keep their share of the weight and contribute zero; that
is an evidence limitation, not proof of poor material performance. Element
screening is a special case: any positive importance enables its exclusion list.
It is not a compound-safety assessment.

Profile edits do not recalculate existing reports or snapshots. New requests may
also retrieve different sources, so changed results may reflect more than changed
weights. See [ranking rules](ranking.md), [literature screening](literature-ranking.md)
and [request interpretation](semantic-intake.md).

## Read and download a report

| View                            | What to inspect                                                                             |
| ------------------------------- | ------------------------------------------------------------------------------------------- |
| **Summary**                     | Main findings, candidate shortlist, reasons for consideration, tradeoffs and evidence gaps. |
| **Technical View**              | Candidate assessments, cited passages, property context and comparisons.                    |
| **Sources**                     | The saved references and their access and provenance details.                               |
| **Search and analysis details** | Search outcomes, applied preferences, calculation details and supporting property records.  |

The main **screening priority** reflects cited application relevance,
demonstrated use and assessed attributes. It is separate from the numerical
ranking of validated property records. Read reported concerns and ties alongside
the score. Percentages, colors and evidence coverage are not confidence estimates
or experimental performance predictions.

Check composition, phase, sample, material role and conditions. A quotation can
support a qualitative interpretation without establishing a numerical property.
Unknown stability, processability or lifetime remains unresolved. Prompts supply
preferences and hints, never scientific evidence. See
[source coverage](scientific-sources.md).

To export, check the sections beside **Summary**, **Technical View** and
**Sources**, choose **Plain text**, **JSON**, **PDF** or **Word (.docx)**, then
select **Download**. Sources is selected by default and can be downloaded alone.
Checkboxes affect downloads, not which tabs you can view. Downloads do not
rerun research.

**Report Format** adjusts verbosity, terminology and document appearance.
Ordinary reports and tracked reports use current formatting preferences;
pinned snapshots keep their recorded format. Formatting does not change the
saved evidence or rankings.

## Inspect structures and download CIF files

Choose **View structure** beside an eligible candidate in Summary or Technical
View, then select a record if several are offered. In JSmol, drag to rotate,
scroll to zoom, or use **Reset view** and **Toggle rotation**. Read the source,
retrieval information and **Structure limitations** before using the file.

**Find reference structures** starts checked in each new prompt composer. It
searches selected supported repositories after an eligible report is saved;
it does not guarantee a match or retrieve coordinates just by opening a report.
An inline **Retry reference lookup** can retry missing or failed discovery.

**Download CIF** or **Download displayed structure** exports the validated
geometry as a derived P1 CIF. It is not a symmetry determination or necessarily
the original source file. **Download original CIF** appears separately only for
supported, validated source attachments.

A **phase match unverified** label means composition matching has not established
the report's exact phase or sample. For supported multi-component candidates,
**Component 1**, **Component 2** and similar entries can show separate bulk
reference structures. They do not represent an assembled interface, core/shell
geometry or particle shape. Viewer bonds are illustrative. Structure lookups
and downloads do not supply property measurements or change the ranking.

Unavailable or failed retrieval does not prove a structure does not exist. The
app does not substitute demonstration structures. See
[structure coverage and safeguards](structures.md) for supported sources,
reference matching and file limitations.
