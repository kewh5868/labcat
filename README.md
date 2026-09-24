# Labcat

**Curious. Clever. Companionable.**

A materials-research assistant in development, built on a scikit-package Level 4
foundation. This initial package contains the Python project layout, package
metadata, licensing, development checks and basic CI. Research, ranking, a
command-line interface and the application UI are not implemented in this snapshot.

## Development

Use Python 3.11 or newer. From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pre_commit install
python -m pre_commit run --all-files
python -m pytest
python -m build
```

On Windows PowerShell, activate with `.\.venv\Scripts\Activate.ps1` instead.
Pre-commit downloads its pinned hook environments on first use. The development
extra provides the Ruff executable used by the local lint hook. Black is the
Python formatter; Flake8, Ruff and the file checks catch additional issues.

The GitHub workflow runs these scaffold checks on Linux with Python 3.13. That
configuration does not establish coverage of other platforms. Core package
imports use only the Python standard library. No CLI command is installed yet.

## Project foundation

See [scaffold provenance](docs/scaffolding.md), [the license](LICENSE.rst), and
[the code of conduct](CODE-OF-CONDUCT.rst). Package metadata lives in
`pyproject.toml`; pinned build requirements are in `requirements/build.lock`.
