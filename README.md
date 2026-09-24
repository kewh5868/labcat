# Labcat

**Curious. Clever. Companionable.**

A public-evidence materials research assistant in development on a scikit-package
Level 4 foundation. This snapshot validates local preferences and reports software
capabilities. Python APIs provide closed model planning, approved provider routes
and an encrypted credential vault. The optional `labcat aws-check --profile NAME
--region REGION` command performs a read-only account check. Scientific retrieval,
ranking, saved connection lifecycle and the application UI are planned; it returns no demonstration materials or scientific evidence.

## Development and status

Use Python 3.11 or newer. From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev,aws,connections]"
labcat status
labcat status --style audit --format json
labcat check-config
python -m pre_commit install
python -m pre_commit run --all-files
python -m pytest
python -m build
```

On Windows PowerShell, activate with `.\.venv\Scripts\Activate.ps1` instead.
`python -m labcat` supports the same commands. Pass `--config preferences.toml`
before a command to load partial TOML preferences. Unknown fields, scientific
properties and policy overrides are rejected. Numeric weights are preferences,
never measurements or scientific confidence. Ordinary status and configuration
commands use the standard library and make no network requests.

Pre-commit downloads pinned environments on first use. Black formats Python;
Flake8, Ruff and file checks provide additional validation. The current CI
configuration targets Linux with Python 3.13; it does not prove other-platform
coverage. See [scaffold provenance](docs/scaffolding.md),
[configuration](docs/configuration.md), [provider boundaries](docs/providers.md), and [the license](LICENSE.rst).
