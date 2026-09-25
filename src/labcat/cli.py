"""Command-line entry points for public-evidence materials triage."""

import argparse
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from labcat import __version__
from labcat.config import load_config
from labcat.service import get_status, render_text


def _workspace_research_preferences(path, connections):
    """Direct CLI runs retain installed source choices and deployment
    bounds."""
    from labcat.developer_settings import DeveloperSettingsStore
    from labcat.source_preferences import SourcePreferencesStore
    from labcat.workspace import WorkspaceSchemaError, WorkspaceStore

    try:
        workspace = WorkspaceStore(path)
    except (OSError, WorkspaceSchemaError):
        raise sqlite3.DatabaseError("Workspace settings are unavailable.") from None
    controls = DeveloperSettingsStore(workspace, connections)
    sources = SourcePreferencesStore(workspace)
    controls.initialize()
    sources.initialize()
    return {
        "research_controls": controls.load(),
        "source_preferences": sources.load(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Public-evidence materials triage")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--config", type=Path, help="Optional local TOML preferences")
    sub = parser.add_subparsers(dest="command", required=True)
    status = sub.add_parser(
        "status", help="Show implemented capabilities and limitations"
    )
    status.add_argument("--style", choices=("pi", "audit"))
    status.add_argument("--format", choices=("text", "json"))
    sub.add_parser("check-config", help="Validate configuration without network access")
    query = sub.add_parser(
        "research", help="Research materials using current public evidence"
    )
    query.add_argument("prompt", help="Research question (preferences, never evidence)")
    query.add_argument("--style", choices=("pi", "audit"))
    query.add_argument("--format", choices=("text", "json", "pdf", "docx"))
    query.add_argument(
        "--output", type=Path, help="Write a report file (required for PDF/Word)"
    )
    query.add_argument(
        "--views", choices=("pi", "audit", "both"), help="Report views to export"
    )
    connection_options = query.add_mutually_exclusive_group()
    connection_options.add_argument(
        "--connections",
        type=Path,
        metavar="WORKSPACE_PATH",
        help="Required workspace with an authenticated model connection",
    )
    connection_options.add_argument(
        "--server",
        action="store_true",
        help="Use the running local backend's account, source and ranking settings",
    )
    query.add_argument(
        "--ranking-profile",
        metavar="PROFILE_ID",
        help="Saved ranking profile for --server (otherwise infer from prompt)",
    )
    aws = sub.add_parser("aws-check", help="Check an explicit AWS profile (read-only)")
    aws.add_argument("--profile", required=True, help="Named AWS CLI/SSO profile")
    aws.add_argument(
        "--region", required=True, help="AWS region for the connection check"
    )
    serve = sub.add_parser("serve", help="Run the optional local browser interface")
    serve.add_argument("--host", choices=("127.0.0.1", "0.0.0.0"), default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
    except (OSError, ValueError) as exc:
        parser.error(f"Configuration error: {exc}")

    if args.command == "check-config":
        print("Configuration valid. Ranking preferences are not scientific evidence.")
    elif args.command == "status":
        report = get_status(config, args.style)
        output_format = args.format or config.presentation.format
        if output_format == "json":
            print(
                json.dumps(
                    report,
                    indent=None if config.presentation.verbosity == "concise" else 2,
                )
            )
        else:
            print(
                render_text(
                    report,
                    config.presentation.terminology,
                    config.presentation.verbosity,
                ),
                end="",
            )
    elif args.command == "research":
        from labcat.connections import ConnectionManager
        from labcat.credentials import ConnectionError
        from labcat.models import ModelError
        from labcat.remote_research import (
            ServerResearchError,
            run_server_research,
        )
        from labcat.research import research

        if args.server and args.config:
            parser.error(
                "Server research uses the application's saved settings; omit --config."
            )
        if args.ranking_profile and not args.server:
            parser.error("--ranking-profile requires --server.")
        connections = ConnectionManager(args.connections) if args.connections else None
        try:
            outcome = (
                run_server_research(args.prompt, args.ranking_profile)
                if args.server
                else research(
                    args.prompt,
                    config,
                    connections=connections,
                    **(
                        _workspace_research_preferences(args.connections, connections)
                        if args.connections
                        else {}
                    ),
                )
            )
        except sqlite3.Error:
            parser.error("Saved workspace research settings are unavailable.")
        except (ConnectionError, ModelError, ServerResearchError) as error:
            parser.error(str(error))
        finally:
            if connections is not None:
                connections.agent.close()
        selected_format = args.format or config.presentation.format
        if args.output or selected_format in {"pdf", "docx"}:
            if not args.output:
                parser.error("PDF and Word exports require --output PATH.")
            from labcat.report_exports import ExportUnavailable, render_download

            views = (
                args.views
                or args.style
                or (
                    "both"
                    if len(config.presentation.outputs) == 2
                    else config.presentation.outputs[0]
                )
            )
            record = {
                **outcome,
                "id": "cli",
                "title": "Materials research",
                "created_at": datetime.now(UTC).isoformat(),
            }
            try:
                content, _, _ = render_download(record, selected_format, views)
                args.output.write_bytes(content)
            except (OSError, ValueError, ImportError, ExportUnavailable) as error:
                parser.error(f"Could not export report: {error}")
            print(f"Report saved to {args.output}")
        elif selected_format == "json":
            print(json.dumps(outcome, indent=2, allow_nan=False))
        else:
            print(
                outcome[
                    (
                        "technical_audit"
                        if (args.style or config.presentation.style) == "audit"
                        else "pi_summary"
                    )
                ]
            )
    elif args.command == "aws-check":
        from labcat.aws import AWSConnectionError, check_connection

        try:
            result = check_connection(args.profile, args.region)
        except AWSConnectionError as exc:
            parser.error(str(exc))
        print(json.dumps(result, indent=2))
    else:
        if not 1 <= args.port <= 65535:
            parser.error("Port must be between 1 and 65535.")
        try:
            import uvicorn

            from labcat.web import create_app
        except ImportError:
            parser.error('Install browser support with: pip install -e ".[web]"')
        uvicorn.run(
            create_app(config),
            host=args.host,
            port=args.port,
            access_log=False,
            proxy_headers=False,
        )
    return 0
