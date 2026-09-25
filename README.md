# Labcat

**Curious. Clever. Companionable.**

Labcat is a local materials research prototype with one Python core for its CLI
and FastAPI service. This snapshot implements bounded public retrieval, reproducible
ranking, cited report exports, saved projects/chats and explicit model connections.
User prompts and model memory are preferences or search hints, never evidence.
Only approved public-source adapters can supply scientific records. Missing evidence
remains unknown; the application provides no private-data or wetlab tools.

The React workspace and portable/native launchers arrive in later snapshots.
The backend serves an actionable missing-frontend response at `/`; `/health` and
the application API work independently. This is a local single-user prototype.

## Run the backend

Use Python 3.11 or newer. From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[web,aws,connections,exports,dev]"
labcat status --style audit
labcat check-config
labcat serve --host 127.0.0.1 --port 8000
```

On Windows PowerShell, activate with `.\.venv\Scripts\Activate.ps1` instead.
Choose an available local port. `python -m labcat` supports the same commands.
`labcat research --help` describes direct-workspace and running-backend research.
New research requires an explicitly verified model connection; hosted inference
also requires explicit consent. Status and configuration validation are offline.
API connection and setup routes are implemented; the onboarding UI is still planned.
No API key or user account is bundled.

TOML settings can change bounded ranking/presentation preferences, but cannot
supply facts or disable fixed research boundaries. Public source coverage determines
whether a request yields ranked candidates, references only or an honest abstention.
Reports preserve source identities, missing data and caveats. This prototype is not
a substitute for experimental validation or a comprehensive literature review.

## Development checks

```bash
python -m pre_commit install
python -m pre_commit run --all-files
python -m pytest
python -m ruff check src tests
python -m build
```

Pinned pre-commit environments are downloaded on first use. Current local checks
do not establish authenticated provider, Docker or other-operating-system coverage.
See [scaffold provenance](docs/scaffolding.md), [the license](LICENSE.rst), and
[the code of conduct](CODE-OF-CONDUCT.rst).
