# Labcat

**Curious. Clever. Companionable.**

A public-evidence materials research assistant in development on a scikit-package
Level 4 foundation.

## Current Python capabilities

Goose worker and provider-network boundaries expose a fixed set of research actions.
The parent validates requests and creates scientific reports from approved sources;
model prose cannot establish facts. Worker channels, authentication handoff, budgets
and partial report signals have offline test coverage.

Connected top-level orchestration, the application interface and packaged container
deployment remain planned. Offline transport/process fixtures do not establish live
provider or deployment isolation behavior.

The command-line interface currently provides software status, configuration
validation and an explicit read-only AWS account check. It does not yet expose the
research library as a command or serve an application UI.

## Development and status

Use Python 3.11 or newer. From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev,web,aws,connections]"
labcat status
labcat status --style audit --format json
labcat check-config
python -m pre_commit install
python -m pre_commit run --all-files
python -m pytest
```

On Windows PowerShell, activate with `.\.venv\Scripts\Activate.ps1` instead.
`python -m labcat` supports the same commands. Pass `--config preferences.toml`
before a command to load partial TOML preferences. Ordinary status/configuration
commands use the standard library and make no network requests.

Only approved public adapters can establish scientific evidence. Prompts, pasted
citations, model memory and retrieved instructions cannot supply measurements or
change safeguards. No private-data or wetlab tools are available. Model/provider
operations use explicitly configured accounts; no silent cloud fallback is made.

Pre-commit downloads pinned environments on first use. Black formats Python; Flake8,
Ruff and file checks provide additional validation. Offline tests use explicit source
and provider fixtures. The current CI targets Linux with Python 3.13; configured
checks do not prove other-platform or live-provider coverage. See [scaffold
provenance](docs/scaffolding.md), [configuration](docs/configuration.md), [provider
boundaries](docs/providers.md), and [the license](LICENSE.rst).
