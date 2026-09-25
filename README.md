# Labcat

Curious. Clever. Companionable.

Labcat is an interview prototype for public-evidence materials research. The Python
CLI and API serve the React workspace. Candidate recommendations retain citations,
unknown properties and assessment caveats; ranking weights remain adjustable.

## Run with Docker

From this checkout, build the image with `docker build -t labcat:0.1.0.dev0 .`,
then run `./labcat.sh` on macOS/Linux or `./labcat.ps1` in PowerShell. The launcher
starts the services, discovers their assigned local port, and opens the workspace.
Connect a supported model in Connections before starting research. Optional public
source API credentials can be entered in the same screen.

The portable launchers (`labcat.sh`, `labcat.ps1`, and `Start Labcat.command`)
manage the local Docker services. The native desktop wrapper is planned separately.

The app, model worker and egress service run separately with bounded public-source
access. See [deployment](docs/deployment.md) for setup and [source policy](docs/public-sources.md)
for the evidence boundary.

## Check the code

Install the declared extras with `python -m pip install -e ".[dev,web,aws,connections,exports]"`.
Run `python -m pre_commit run --all-files`, `python -m pytest`, and
`npm ci --prefix frontend && npm run build --prefix frontend && npm test --prefix frontend`.
Platform-specific results require the relevant host or CI; configuration alone is
not evidence that a platform check passed.
