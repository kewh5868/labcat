# Developer guide

For ordinary use, follow [Docker installation](installation.md). This page is
for working on the source and running checks.

## Run a development server

For code development on the host (not required for the Docker instructions above),
use Python 3.11+ and Node 22.12+ (CI uses Node 24):

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[web,aws,connections,exports,dev]'
npm ci --prefix frontend
npm run build --prefix frontend
labcat serve
```

Open <http://127.0.0.1:8000>. On Windows use `py -m venv .venv` and
`.venv\Scripts\Activate.ps1`. The base CLI requires no third-party runtime
packages. For research, choose `--server` to use an already configured backend
at its fixed same-machine address `127.0.0.1:8000`, or `--connections WORKSPACE_PATH`
to use an explicitly saved and accessible API/Bedrock connection from Python.
`--server` uses the app's saved settings and cannot be combined with `--config`
or `--connections`. ChatGPT research uses the Docker backend and its Goose worker.

```bash
python -m pre_commit run --all-files
python -m pytest
npm test --prefix frontend
npm run build --prefix frontend
ruff check .
python -m build
python scripts/check_distributions.py
python scripts/smoke_container.py --workspace
```

The scikit-package Level 4 pre-commit checks cover Python formatting and linting,
YAML/TOML validation, text formatting, merge conflicts, file-name case conflicts,
and large-file checks. Black is the Python formatter; Ruff adds application lint
rules. Upstream vendor files and reviewed binary assets have documented exceptions.
Run `python -m pre_commit install` once in your development clone to run the hooks
before each commit. After a hook edits files, review the changes and rerun it.
The application tests and distribution checks above run separately from the hooks.
See [scaffold and hook provenance](scaffolding.md).

See the [three-page design note](design-note.pdf), [evaluation](evaluation.md),
[validation record](validation.md), and [preserved earlier layout](ui-layouts.md).
Hard evidence rules cannot be overridden through settings, prompts, models or
retrieved content. This is a single-user loopback service, not shared lab hosting.

## Build the documentation

Documentation is built separately from the application. From the repository root:

```sh
python -m pip install -r requirements/docs.txt
python -m mkdocs serve
```

Open the local address printed by MkDocs. Before publishing, run:

```sh
python -m mkdocs build --strict
```

The generated site goes into the ignored `.local/docs-site/` directory. The
Documentation workflow validates pull requests and publishes documentation changes
on `main` to [GitHub Pages](https://kewh5868.github.io/labcat/). A documentation
build does not start the app or run research.

For native application builds, see the
[desktop build guide](https://github.com/kewh5868/labcat/blob/main/desktop/README.md).
The source uses the BSD-3-Clause license; bundled third-party data and libraries
retain their own license notices.
