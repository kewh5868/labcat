# Example research prompts

These are starting questions to copy into a new chat, not demonstrations with
precomputed answers. Results depend on the selected model, enabled public
sources and available evidence. A useful result may be a small shortlist,
explicitly missing information, or a clarification question.

Complete [model setup](onboarding.md), then use **Infer from prompt** for a first
run or choose a saved profile deliberately. Afterward, inspect the profile the
report actually used. The [user guide](user-guide.md) explains criteria, history,
exports and structure viewing.

## Oxide dielectrics for thin-film capacitors

**Goal:** identify materials worth reviewing for a thin-film application while
keeping bulk calculations separate from film and device evidence.

```text
Find oxide dielectric candidates to review for thin-film capacitors.
Prioritize high dielectric response and a band gap of at least 3 eV as my
screening preferences. Compare evidence for room-temperature phase stability
and operation under an electric field. Keep bulk calculated properties
separate from measured thin-film properties. Identify missing evidence for
leakage, dielectric loss and processing compatibility.
```

The 3 eV minimum is an example preference, not a universal material requirement.
In **Technical View**, inspect the source method, units and conditions. In
**Search and analysis details**, check which properties could be scored and
which remain unavailable. A bulk dielectric value alone does not establish
thin-film suitability.

Try this follow-up in the same chat:

```text
For the retained candidates, look for public evidence specific to thin films.
Which reported phases, film conditions and device observations support the
comparison, and which questions remain unresolved?
```

To explore different priorities, save a custom profile with greater relative
importance for **Band gap** and **Operational stability**, then explicitly select
it for a new request. Check whether accepted evidence supports any change in
order; an increased stability weight cannot supply missing lifetime data.

## Perovskite absorbers for a tandem top cell

**Goal:** review the absorber's role in a perovskite/silicon tandem, rather than
mixing it with transport layers, additives or precursor materials.

```text
Find perovskite absorber compositions reported for the top cell of a
perovskite/silicon tandem solar cell. Use a band-gap target around 1.7 eV as
my preference. Prioritize room-temperature phase stability and operational
stability under illumination. Distinguish fabricated-device evidence from
simulation or proposals, and preserve each source's reported composition.
Identify where operating conditions or duration are missing.
```

The 1.7 eV target is an example user preference, not a claim of an optimum.
Check the applied target and tolerance, and review any element exclusions in
the selected profile. In the report, inspect whether each cited composition
actually plays the requested absorber role and whether stability observations
match the requested conditions. A device result is not automatically an
intrinsic property of its absorber.

Try this follow-up:

```text
Revisit the retained absorber candidates with emphasis on illumination
stability. For each, distinguish an observed degradation concern from an
absence of relevant tests. Keep composition, device configuration, test
conditions and duration attached to the source discussion.
```

For a second priorities comparison, save and explicitly select a profile with
higher **Operational stability** importance. Use **Earlier questions** to compare
report revisions. Source retrieval may also change between runs, so inspect the
citations as well as the ordering.

## Quantum-dot coatings for greenhouse glazing

**Goal:** find public research on a particular light-conversion role while
keeping optical observations, coating durability and crop outcomes distinct.

```text
Find quantum-dot materials studied as luminescent coatings or films for
greenhouse glazing. Focus on converting incident light for plant-lighting
applications, rather than electrically driven LEDs. Review reported optical
behavior, solution processability and stability under light and moisture.
Distinguish measurements of isolated dots from measurements of a coating,
and identify whether any source actually reports a greenhouse or plant study.
```

Inspect whether the source supports the complete application or only a related
optical use. Check the actual test conditions and unresolved criteria; a
promising optical passage does not establish coating lifetime or crop benefit.
If a composite candidate has a structure panel, component CIFs are bulk
references, not a model of the assembled quantum dot or coating.

Try this follow-up:

```text
Which retained candidates have public evidence for a processed film or
coating under illumination and moisture? Separate demonstrated application
use from proposals, and list the evidence still needed before comparing
coating durability.
```

A custom profile can give **Solution processability** and **Operational stability**
more importance. These may inform cited qualitative assessments while remaining
unavailable in the separate numerical property ranking. Check the report rather
than assuming that a selected attribute has been measured.

## Keep a useful comparison

Pin a snapshot before changing priorities if you want a fixed project reference.
Save the new profile and select its name in the next prompt; changing settings
alone does not update the previous report. Compare candidate identities, source
passages, evidence gaps and recorded weights, then export the relevant views
with **Sources** included.

When the report lacks evidence, narrow the requested role or conditions and
check [public-source coverage](scientific-sources.md). A failed search should
remain a stated limitation, not become evidence against a material or a reason
to fill the gap with an assumed value.
