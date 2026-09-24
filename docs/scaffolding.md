# Package scaffold provenance

Adapted from the official
[scikit-package-system Level 4 template](https://github.com/scikit-package/scikit-package-system)
at commit `b4e742715726afd0d2087fe4216081aab1e79a31`, rendered on 2026-09-09
with Cookiecutter 2.7.1. The installed scikit-package version was 0.3.1; its
`package create system` command delegates to that template. `cookiecutter.json`
retains the project fields.

This scaffold keeps the `src` layout, setuptools packaging, license and
contributor metadata, build requirements and development-check foundation.
Demonstration vector operations and their scientific-library dependencies are
omitted. The package currently exposes its installed version. It does not yet
retrieve evidence, rank materials or provide an application interface.

The development version is explicit in `pyproject.toml`; no Git-derived version
plugin is required. Runtime imports use the Python standard library.

## Development checks

The actual scikit-package Level 4 hook family runs through pre-commit: YAML/TOML
and file hygiene checks, docformatter, Black, Flake8, nbstripout and Prettier.
Tool revisions are pinned. Private-key detection and Ruff lint supplement those
checks. Black is the sole Python formatter. Black, Flake8 and Ruff use an
88-character line width; docformatter wraps summaries and descriptions at 72.
There are no notebooks in this scaffold, so nbstripout has nothing to strip.

The shared hook configuration reserves exclusions for generated assets and
third-party files as they are introduced. Application code, tests and authored
documentation remain covered. Run the hooks and pytest before committing, and
build both wheel and source distributions when packaging changes.

The initial GitHub workflow checks the scaffold on Linux with Python 3.13.
Cross-platform and application-specific checks can be added alongside their
implementations. An unexecuted workflow is not a recorded validation result.
