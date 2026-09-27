---
title: Get started
---

<div class="labcat-intro" markdown>

<img src="assets/labcat-mark.png" alt="Labcat cat and chemistry flask icon" width="112" height="112">

# Research materials with Labcat

**Curious. Clever. Research Companion.**

Labcat is a platform and API for intelligent materials research. Explore public
materials science data, screen and rank cited candidates for your application,
and keep your research organized. Ask a question, customize your ranking
priorities, and review the findings, supporting sources, and available crystal
structures.

[First-run walkthrough](first-run.md){ .md-button .md-button--primary }
[Explore examples](examples.md){ .md-button }

</div>

## Install and open

New to Labcat? The [first-run walkthrough](first-run.md) explains what to type,
what to click, and what to expect from installation through your first download.
Use the quick start below if you are already comfortable with Docker.

**You need:** Git and a running local Docker installation. Use
[Docker Desktop](https://docs.docker.com/desktop/) on Mac or Windows, or
[Docker Engine and Compose](https://docs.docker.com/engine/install/) on Linux.
On Windows, select Linux containers. Desktop installation from source also needs
**Node 24, Rust/Cargo and OS build tools**; see [desktop prerequisites](installation.md#desktop-prerequisites).
Browser mode needs no host Python, Node or Rust.

### 1. Get the code and build once

Run these commands in Terminal or PowerShell:

```sh
git clone https://github.com/kewh5868/labcat.git
cd labcat
docker build -t labcat:0.1.0.dev0 .
```

The first build downloads dependencies and can take several minutes. It builds
for your computer's architecture, including Apple Silicon. Wait for it to finish.

### 2. Open the workspace

=== "Mac / Linux"

    ```sh
    ./labcat.sh
    ```

=== "Windows PowerShell"

    ```powershell
    .\labcat.cmd
    ```

On first launch, press **Enter** for **Desktop**, or choose **2** for **Browser**.
The launcher remembers the choice. Desktop installs a native app from supplied
binaries or builds the source; Browser opens the local address it prints. Both
use Docker. Run `./labcat.sh --choose` or `.\labcat.cmd -Choose` to choose again.
Keep Docker running while using Labcat.

### 3. Connect a model

Labcat's developer currently recommends **ChatGPT account sign-in** because it
is the application's most thoroughly tested model connection.

In setup, choose **Model provider**. Sign in with ChatGPT, use the
[native Claude Code terminal flow](onboarding.md#claude-code-account-sign-in), or
connect a supported API provider. Select a model, enable consent for sending
research context, then choose **Save and test connections**. Review the optional
public-source settings, then finish setup. Claude Code offers configured model
aliases; native sign-in detection does not test entitlement or inference.

A Materials Project API key is optional. The workspace runs locally, while AI
research uses the provider you connect and may consume its allowance or incur
charges. [Connection help](onboarding.md)

**Already installed?** Start Docker and repeat step 2 from your Labcat folder.
For native desktop use, supplied image archives, direct Compose commands, and
updates, see [all installation options](installation.md).

## Ask your first question

Select **New chat** and paste one of these prompts:

### Thin-film transistor insulators

> I need an oxide for a very thin transistor insulating layer. Put a high
> dielectric constant ahead of ease of manufacture, but include leakage and
> room-temperature phase stability in the comparison.

### Perovskite tandem top cells

> Compare metal-halide perovskite absorber compositions used in demonstrated
> perovskite/silicon tandem top cells. Prioritize operational stability and a
> suitable optical band gap, and distinguish device evidence from predictions.

### Quantum-dot greenhouse coatings

> Compare quantum-dot material systems for greenhouse films that convert UV or
> blue light into red light. Consider photoluminescence yield, outdoor stability,
> reabsorption, and reported environmental concerns. Look for core and shell
> reference structures separately when appropriate.

These are starting questions, not preset results. Returned candidates depend on
available public sources and the selected model. [See what to inspect and how to
follow up](examples.md).

## Read and refine the result

1. **Summary:** start with the findings and candidate shortlist.
2. **Technical View:** inspect comparisons, available property evidence, and gaps.
3. **Sources:** follow the citations. Use **View structure** when a reference
   structure is available; its phase may differ from a working device.
4. **Search Criterion:** adjust or select a ranking profile, then run a follow-up
   comparison. A changed weight only helps distinguish candidates when the
   evidence and supported scoring allow it.

Select the sections you want beside the report tabs, choose an export format,
and download. [Tour the workspace](user-guide.md)

[Ranking details](ranking.md) · [Validation and limitations](validation.md)
