<p align="center">
  <img src="docs/assets/labcat-mark.png" alt="Labcat cat and chemistry flask icon" width="128" height="128">
</p>

# Labcat

**Curious. Clever. Research Companion.**

Labcat is a platform and API for intelligent materials research. Explore public
materials science data, screen and rank cited candidates for your application,
and keep your research organized. Ask a question, customize your ranking
priorities, and review the findings, supporting sources, and available crystal
structures.

**[Get started →](https://kewh5868.github.io/labcat/)** ·
[First-run walkthrough](https://kewh5868.github.io/labcat/first-run/) ·
[User guide](https://kewh5868.github.io/labcat/user-guide/) ·
[Examples](https://kewh5868.github.io/labcat/examples/)

[![Package checks](https://github.com/kewh5868/labcat/actions/workflows/ci.yml/badge.svg)](https://github.com/kewh5868/labcat/actions/workflows/ci.yml)

## Choose desktop or browser

Install and start [Docker Desktop](https://docs.docker.com/desktop/) on Mac or
Windows, or [Docker Engine with Compose](https://docs.docker.com/engine/install/)
on Linux. Windows must use Linux containers.

```sh
git clone https://github.com/kewh5868/labcat.git
cd labcat
docker build -t labcat:0.1.0.dev0 .
```

The final `.` is required: it tells Docker to build using the current `labcat`
folder. Include the space before it.

Then open the app:

| Mac / Linux   | Windows PowerShell |
| ------------- | ------------------ |
| `./labcat.sh` | `.\labcat.cmd`     |

On first launch, press **Enter** for **Desktop**, or choose **2** for **Browser**.
The launcher remembers your choice. Desktop installs a native app for your user;
from source it needs **Node 24, Rust/Cargo and OS build prerequisites**.
[Prepare desktop prerequisites](https://kewh5868.github.io/labcat/installation/#desktop-prerequisites).
Browser mode needs no host Python, Node or Rust. Both modes use Docker.
Use `--choose` on Mac/Linux or `-Choose` on Windows to choose again.

Connect a model provider in first-time setup, select a model, and save and test
the connection. Start a **New chat** and ask your materials question.
**Model access:** Hosted research requires a provider account with access to a
model that supports agent tasks and tool calls. For ChatGPT sign-in, your account
needs Codex access and remaining usage allowance or credits. API access has
separate billing and limits. See OpenAI's [sign-in options](https://learn.chatgpt.com/docs/auth)
and [Codex usage limits](https://learn.chatgpt.com/docs/pricing).

For exact commands and in-app clicks, follow the
[first-run walkthrough](https://kewh5868.github.io/labcat/first-run/).
For supplied image bundles, native desktop options, troubleshooting, and updates,
see the [installation guide](https://kewh5868.github.io/labcat/installation/).

## Try a question

> I need an oxide for a very thin transistor insulating layer. Put a high
> dielectric constant ahead of ease of manufacture, but include leakage and
> room-temperature phase stability in the comparison.

Explore the **Summary**, **Technical View**, and **Sources**, then try changing a
ranking priority. More [example prompts](https://kewh5868.github.io/labcat/examples/)
cover tandem solar cells and quantum-dot coatings.

Labcat is an **interview prototype**. Results are screening aids, not validated
material selections. Source coverage varies; missing measurements and unavailable
structures remain explicit. Read [how ranking works](docs/ranking.md) and the
[validation record](docs/validation.md).

## Development

[Developer guide](docs/development.md) · [Architecture](docs/architecture.md) ·
[Research safeguards](docs/research-safeguards.md) · [BSD-3-Clause license](LICENSE.rst)
