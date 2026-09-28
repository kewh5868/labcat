# Developer notes

For ordinary use, follow [Install & setup](first-run.md). Labcat shares one
Python research core between its CLI and FastAPI service. React supplies the
interface; the optional Tauri desktop shell opens that interface from Docker.

## Work on the source

Host development requires **Python 3.11+** and **Node 22.12+ with npm**; CI uses
Node 24. From a clone of the repository:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[web,connections,exports,dev]'
npm ci --prefix frontend
npm run build --prefix frontend
labcat serve
```

On Windows, create the environment with `py -m venv .venv` and activate it with
`.venv\Scripts\Activate.ps1`. Open <http://127.0.0.1:8000> for the host development
server. Account-based research also requires the Docker backend and its Goose
worker; the host server alone does not provide that worker.

The [CLI](https://github.com/kewh5868/labcat/blob/main/src/labcat/cli.py) and
[API routes](https://github.com/kewh5868/labcat/blob/main/src/labcat/web.py) use the
same core. Run `labcat --help` or `labcat research --help` for CLI options.
The service is intended for a single user on the local machine. Prompts and
retrieved content cannot grant access to private data or create scientific facts.

A second clone normally reuses the same Docker workspace and installed native
app. Use an isolated test environment when you need a fresh installation.
Keep credentials, workspace databases and private test artifacts out of Git.

## Check a change

Install the configured scikit-package/pre-commit hooks once:

```sh
python -m pre_commit install
```

Before committing, run the hooks and application tests. Review any files changed
by formatting hooks, then rerun the hooks:

```sh
python -m pre_commit run --all-files
python -m pytest
python -m ruff check .
npm test --prefix frontend
npm run build --prefix frontend
```

For packaging changes, also run `python -m build` and
`python scripts/check_distributions.py`. Container and native-app checks need
the corresponding runtime; CI configuration alone is not a passing result.
See the [test workflow](https://github.com/kewh5868/labcat/blob/main/.github/workflows/ci.yml)
and [native build guide](https://github.com/kewh5868/labcat/blob/main/desktop/README.md).

## Preview the documentation

```sh
python -m pip install -r requirements/docs.txt
python -m mkdocs serve
```

Open the address printed by MkDocs. Run `python -m mkdocs build --strict` before
publishing. The generated site is stored in the ignored `.local/docs-site/`
folder; the documentation workflow deploys updates from `main` to GitHub Pages.

## Technical records

The concise guide covers normal use. Detailed implementation and historical
validation records remain available in the repository:

- [Architecture](https://github.com/kewh5868/labcat/blob/main/docs/architecture.md)
  — components, data flow and trust boundaries.
- [Ranking](https://github.com/kewh5868/labcat/blob/main/docs/ranking.md) and
  [candidate screening](https://github.com/kewh5868/labcat/blob/main/docs/literature-ranking.md)
  — calculations, missing evidence and saved preferences.
- [Evaluation](https://github.com/kewh5868/labcat/blob/main/docs/evaluation.md) and
  [validation history](https://github.com/kewh5868/labcat/blob/main/docs/validation.md)
  — test procedures and dated results.
- [Deployment](https://github.com/kewh5868/labcat/blob/main/docs/deployment.md)
  — bundles, workspace storage and troubleshooting.

Labcat uses the BSD-3-Clause license. Bundled libraries and public datasets
retain their own [third-party notices](https://github.com/kewh5868/labcat/blob/main/third_party/README.md).
