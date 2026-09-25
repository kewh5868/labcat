# Package scaffold provenance

Generated on 2026-09-09 using Cookiecutter 2.7.1 from the official
[scikit-package-system Level 4 template](https://github.com/scikit-package/scikit-package-system)
at commit `b4e742715726afd0d2087fe4216081aab1e79a31`.
The installed scikit-package version was 0.3.1. Its `package create system`
command delegates to this template. We rendered the same template through
Cookiecutter's Python API into a temporary directory, then adapted the output.
`cookiecutter.json` retains the chosen project fields; no GitHub owner is assumed.

Retained the `src` layout, setuptools backend, contributor/license metadata,
requirements directory and test/CI foundation. Replaced demonstration vector
math and NumPy/Matplotlib dependencies with the actual application shell.
Core runtime has no third-party dependencies; web and AWS are optional extras.
The browser shell uses React/TypeScript and Vite. Its compiled assets are bundled
into the wheel and served by FastAPI; Node is a build-time dependency only.

Use one explicit development version until releases exist. Removed the template's
Git-versioning plugin and conflicting static version settings. Consolidated Python
lint into Ruff initially and replaced externally delegated CI with a small workflow
that is reviewable in this repository. Project dependency metadata lives in
`pyproject.toml`; runtime locks support container builds.

No remote repository or public package has been created. The generated
BSD-3-Clause license remains a template default to revisit before publication.
Do not run template updates blindly: review changes against the privacy,
configuration, packaging and dependency decisions here.

## Pre-commit checks

The repository now runs the official Level 4 hook family through pre-commit:
file hygiene and YAML/TOML validation, Black, Flake8, docformatter, nbstripout,
and Prettier. Tool revisions are pinned in `.pre-commit-config.yaml`; the
Prettier dependency is pinned rather than using the template's floating range.
A private-key check supplements the template hooks. Ruff retains the existing
application lint/import rules; Black is the sole Python formatter.

The checked-in configuration follows the
[current Level 4 template](https://github.com/scikit-package/scikit-package-system/blob/main/%7B%7B%20cookiecutter.github_repo_name%20%7D%7D/.pre-commit-config.yaml)
and the [official pre-commit guidance](https://scikit-package.github.io/scikit-package/support/frequently-asked-questions.html#how-is-pre-commit-used-in-each-level).
Black and Flake8 use the application's 88-character line width; docformatter
wraps descriptions and summaries at 72. No notebook files are currently present,
so nbstripout legitimately has no files to check. Level 5-only requirements,
such as blocking direct commits to main, are not part of this Level 4 setup.

Do not reformat upstream JSmol sources, licensed fonts/notices or generated static
output. The hook configuration excludes those paths. Reviewed cat sprite sheets
and application icons have explicit large-file exceptions; other application
files still pass the 500 KiB gate. The public scientific snapshot retains its
retrieved JSON bytes rather than being rewritten by Prettier. Application code,
tests and authored documentation remain covered.

Run `python -m pre_commit run --all-files` after installing the development extra.
This checks tracked files. During preparation, also pass any new, untracked files
explicitly with `--files`; do not stage private files merely to include new code.
Install the Git hook once with `python -m pre_commit install` in a development
clone. A passing hook run does not replace pytest, frontend tests, a frontend
build, distribution inspection or platform-specific application checks.
