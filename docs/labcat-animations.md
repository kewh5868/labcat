# Labcat animations

Labcat's optional mascot illustrations are decoration. They do not participate
in research, ranking, account connections, reports, exports, or structure viewing.

## Turn the feature off

Set `ENABLE_LABCAT_MASCOTS = false` in
[`frontend/src/labcatMascotConfig.ts`](https://github.com/kewh5868/labcat/blob/main/frontend/src/labcatMascotConfig.ts), then
rebuild the frontend. This is the single source switch for every placement.
Alternatively, disable it for a particular frontend build:

```sh
VITE_LABCAT_MASCOTS=false npm run build --prefix frontend
```

PowerShell:

```powershell
$env:VITE_LABCAT_MASCOTS = 'false'
npm run build --prefix frontend
Remove-Item Env:VITE_LABCAT_MASCOTS
```

The flag is read **at build time**. Setting an environment variable only on a
running server does not change already-built assets. For Docker builds, changing
the source constant is the simplest option; then use the normal image rebuild
and startup procedure. Refresh the app after installing the new frontend.

Disabled mascots render nothing: no image requests, animation timers, or motion
listeners are created, and the extra header column disappears. The optional PNGs
may still be present in a build's static directory, but they are not requested.
Removing the feature requires only its component/configuration/styles, sprite
folder and placement imports; there are no backend migrations or dependencies.

## Scenes and triggers

The six PNG sheets are in
[`frontend/public/assets/labcat/`](https://github.com/kewh5868/labcat/blob/main/frontend/public/assets/labcat/).
Each has eight equal square cells, four columns by two rows, read left-to-right,
then top-to-bottom. Images use actual alpha transparency and are displayed at
48–104 CSS pixels in the app. CSS moves a sheet behind a fixed square viewport;
JavaScript does not render individual frames. There is no sound or flashing.

| Sheet            | Placement and behavior                                                                                                                                                                                                         |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `beaker.png`     | Research progress holds the first pose still and changes only the liquid color. This is an activity illustration, not a percentage or time estimate. Frames 7–8 bubble over after a newly returned complete or partial report. |
| `wires.png`      | Connections header: plugs join, a small comic smoke puff appears, and the unharmed cat smooths its fur.                                                                                                                        |
| `crystal.png`    | Search Criterion header: magnifying-glass inspection of a crystal.                                                                                                                                                             |
| `typewriter.png` | Report Format header: typing and carriage return.                                                                                                                                                                              |
| `computer.png`   | Retained asset only; no longer displayed in chat.                                                                                                                                                                              |
| `nap.png`        | Retained asset only; no longer displayed in chat.                                                                                                                                                                              |

The desk and nap PNGs and their original generation prompts remain available
for future reuse. [`nap-sequence.json`](https://github.com/kewh5868/labcat/blob/main/frontend/public/assets/labcat/nap-sequence.json)
records the frame order, original 4.8-second playback, held sleeping frame and
previous two-minute idle trigger. Nothing in the application loads this metadata
or starts the nap sequence.

The chat page has no persistent mascot or idle sequence. It installs no activity
listeners or idle timers. The processing beaker remains visible while a research
request is running. Background tabs pause animations. Reduced-motion preferences
show a static first pose for active processing and page mascots, and suppress
the completion flourish. Print layouts omit all mascots.

The processing pose uses a fixed first frame plus a duplicate clipped to the liquid
inside the flask. Only that clipped layer changes hue; neither the cat nor the
vessel changes size or position. If the beaker artwork is replaced, check this
liquid mask against the new first frame before shipping it.

The crystal scene uses its own frame alignment in `labcatMascot.css`. Each pose
is registered to the first frame's table center and front edge, using proportional
translations and a clip for its source cell. This removes the vertical jump at
the second sprite row without changing the illustration or its intended head,
paw and magnifier movements. If `crystal.png` is replaced, recalibrate all eight
poses against that fixed table anchor and check the last-to-first transition.
Check at 104, 72 and 56 CSS pixels, including reduced motion and paused playback.

The completion flourish appears briefly in the chat header for 2.4 seconds, then
disappears, without delaying the response or navigation. Loading saved history, clarification/refusal replies,
and failed requests do not trigger it. A partial report can complete a request;
the illustration does not imply scientific completeness, verified suitability,
or full source availability. Existing progress text remains authoritative.

All mascot content is hidden from assistive technology, ignores pointer events,
and has no interactive descendants. A failed sprite request quietly removes that
decoration. Timers and listeners are cleaned up on unmount and image failure.

## Assets and maintenance

The sheets were generated with the built-in image-generation tool using the
existing Labcat mark as a style reference. The approved beaker sheet served as
the character reference for the other scenes; the computer sheet also guided
the nap sequence. The brand mark itself was not replaced. The final generation
prompts are saved in
[`prompts.json`](https://github.com/kewh5868/labcat/blob/main/frontend/public/assets/labcat/prompts.json).

Maintain the four-by-two layout, transparent gutters, fixed framing and character
identity when replacing a sheet. The CSS uses proportions rather than hard-coded
pixel offsets, so sheets can have different resolutions with the same 2:1 aspect
ratio. Keep files local and small; do not add remote animation dependencies or
model requests. The six current sheets total approximately 5.9 MiB on disk.

Focused checks:

```sh
cd frontend
node --test tests/labcatMascotDom.test.mjs tests/mascotPlacementsDom.test.mjs tests/researchProgressDom.test.mjs
```

These cover the off-switch, motion preferences, visibility, absence of dormant
chat animation, image failure, cleanup, and honest completion signals. Responsive browser checks
also verify that decorations do not cover headings or controls. Research quality
testing remains independent of these illustrations.
