"""Command-line configuration and software capability status."""

import argparse
import json
from pathlib import Path

from labcat import __version__
from labcat.config import load_config
from labcat.service import get_status, render_text


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
    aws = sub.add_parser("aws-check", help="Check an explicit AWS profile (read-only)")
    aws.add_argument("--profile", required=True, help="Named AWS CLI/SSO profile")
    aws.add_argument(
        "--region", required=True, help="AWS region for the connection check"
    )
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
    elif args.command == "aws-check":
        from labcat.aws import AWSConnectionError, check_connection

        try:
            result = check_connection(args.profile, args.region)
        except AWSConnectionError as exc:
            parser.error(str(exc))
        print(json.dumps(result, indent=2))
    return 0
