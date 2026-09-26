<p align="center">
  <img src="docs/assets/labcat-mark.png" alt="Labcat cat and chemistry flask icon" width="128" height="128">
</p>

# Labcat

**Curious. Clever. Companionable.**

Labcat helps you explore materials for an application, compare cited candidates,
and keep your research organized. Ask a question, adjust your ranking priorities,
and review the findings, supporting sources, and available crystal structures.

**[Get started →](https://kewh5868.github.io/labcat/)** ·
[First-run walkthrough](https://kewh5868.github.io/labcat/first-run/) ·
[User guide](https://kewh5868.github.io/labcat/user-guide/) ·
[Examples](https://kewh5868.github.io/labcat/examples/)

[![Package checks](https://github.com/kewh5868/labcat/actions/workflows/ci.yml/badge.svg)](https://github.com/kewh5868/labcat/actions/workflows/ci.yml)

## Run with Docker

Install and start [Docker Desktop](https://docs.docker.com/desktop/) on Mac or
Windows, or [Docker Engine with Compose](https://docs.docker.com/engine/install/)
on Linux. Windows must use Linux containers.

```sh
git clone https://github.com/kewh5868/labcat.git
cd labcat
docker build -t labcat:0.1.0.dev0 .
```

Then open the app:

| Mac / Linux             | Windows PowerShell      |
| ----------------------- | ----------------------- |
| `./labcat.sh --browser` | `.\labcat.cmd -Browser` |

Connect a model provider in first-time setup, select a model, and save and test
the connection. Start a **New chat** and ask your materials question.
The Docker route does not require Python, Node, or Rust on your computer.
Local workspace processing uses your selected AI provider; research may consume
its allowance or incur charges.

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
