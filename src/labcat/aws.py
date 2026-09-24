"""Optional AWS credential readiness.

No inference or resource provisioning.
"""

import re

# Exact MantleResponses entries/aliases in pinned Goose 1.50.0 bedrock.rs.
# This release supports AWS-session Converse only, without Mantle bearer tokens.
_MANTLE_GPT = {"gpt-5.5", "gpt-5.4", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"}
_MANTLE_GEMMA = {"google.gemma-4-31b", "google.gemma-4-26b-a4b", "google.gemma-4-e2b"}


def requires_mantle(model: str) -> bool:
    """Mirror the pinned Goose routes requiring unsupported bearer
    credentials."""
    if model in _MANTLE_GEMMA:
        return True
    base = model.removeprefix("openai.")
    base = re.sub(r"-(none|low|medium|high|xhigh)$", "", base, flags=re.IGNORECASE)
    return base in _MANTLE_GPT


class AWSConnectionError(RuntimeError):
    """A safe, actionable connection error containing no credential
    details."""


def profile_options() -> dict:
    """List local profile names and SDK region metadata, without
    resolving keys."""
    result = {
        "profiles": [],
        "regions": [],
        "setup": {
            "commands": [],
            "documentation_url": (
                "https://docs.aws.amazon.com/cli/latest/userguide/"
                "cli-configure-sso.html"
            ),
            "message": (
                "Use a dedicated profile provisioned inside the application container. "
                "Do not mount host folders or copy personal AWS caches. "
                "No AWS password is collected here. "
                "Bedrock runs model planning in AWS; workspace hosting remains local."
            ),
        },
    }
    try:
        import boto3

        session = boto3.Session()
        result["profiles"] = sorted(
            name
            for name in session.available_profiles
            if isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_.@+-]{1,128}", name)
        )[:100]
        result["regions"] = sorted(
            region
            for region in session.get_available_regions("bedrock")
            if isinstance(region, str) and re.fullmatch(r"[a-z0-9-]{1,64}", region)
        )[:100]
    except Exception:
        result["setup"]["message"] = (
            "AWS profiles could not be listed. Ask your site administrator to "
            "provision a dedicated profile inside the application container. "
            "Do not mount host AWS directories."
        )
    return result


def model_options(profile: str, region: str) -> list[dict]:
    """Read bounded foundation/profile catalogs, without invoking any
    model."""
    _validate_connection(profile, region)
    try:
        import boto3
        from botocore.config import Config
        from botocore.exceptions import ClientError

        session = boto3.Session(profile_name=profile, region_name=region)
        client = session.client(
            "bedrock",
            config=Config(
                connect_timeout=5,
                read_timeout=5,
                retries={"mode": "standard", "total_max_attempts": 1},
                ignore_configured_endpoint_urls=True,
            ),
        )
        try:
            values = client.list_foundation_models(byOutputModality="TEXT").get(
                "modelSummaries", []
            )
            if not isinstance(values, list):
                raise ValueError("Unsupported model catalog")
            # Cross-region models often require the returned inference-profile ID,
            # which is different from the underlying foundation-model ID.
            profiles, seen_tokens, token = [], set(), None
            for _ in range(2):
                try:
                    page = client.list_inference_profiles(
                        maxResults=100, **({"nextToken": token} if token else {})
                    )
                except ClientError as error:
                    if (
                        error.response.get("Error", {}).get("Code")
                        != "AccessDeniedException"
                    ):
                        raise
                    # Keep existing foundation-only accounts usable. Never guess
                    # profile IDs when the selected account cannot list them.
                    break
                rows = page.get("inferenceProfileSummaries")
                if not isinstance(rows, list) or len(rows) > 100:
                    raise ValueError("Unsupported inference-profile catalog")
                profiles.extend(
                    {
                        "modelId": row.get("inferenceProfileId"),
                        "modelName": row.get("inferenceProfileName"),
                    }
                    for row in rows
                    if isinstance(row, dict) and row.get("status") == "ACTIVE"
                )
                token = page.get("nextToken")
                if token is None:
                    break
                if (
                    not isinstance(token, str)
                    or not re.fullmatch(r"\S{1,2048}", token)
                    or token in seen_tokens
                ):
                    raise ValueError("Invalid inference-profile pagination")
                seen_tokens.add(token)
        finally:
            client.close()
        models = [
            {
                "id": row["modelId"],
                "label": (
                    row["modelName"]
                    if isinstance(row.get("modelName"), str)
                    and 1 <= len(row["modelName"].strip()) <= 200
                    and all(ord(c) >= 32 for c in row["modelName"])
                    else row["modelId"]
                ),
            }
            for row in [*profiles, *values[:200]]
            if isinstance(row, dict)
            and isinstance(row.get("modelId"), str)
            and re.fullmatch(r"[A-Za-z0-9_.:/-]{1,200}", row["modelId"])
            and not requires_mantle(row["modelId"])
        ]
        return list({row["id"]: row for row in models}.values())
    except Exception:
        raise AWSConnectionError(
            "AWS models could not be listed. Check the profile, region "
            "and Bedrock catalog permissions."
        ) from None


def _validate_connection(profile: str, region: str):
    if not isinstance(profile, str) or not re.fullmatch(
        r"[A-Za-z0-9_.@+-]{1,128}", profile
    ):
        raise AWSConnectionError("Use a nonempty named AWS profile without spaces.")
    if not isinstance(region, str) or not re.fullmatch(r"[a-z0-9-]{1,64}", region):
        raise AWSConnectionError("Supply an AWS region, for example us-west-2.")


def check_connection(profile: str, region: str) -> dict[str, str]:
    """Use an explicit named profile to call STS, without returning
    identity data."""
    _validate_connection(profile, region)
    try:
        import boto3
        from botocore.config import Config
        from botocore.exceptions import BotoCoreError, ClientError, ProfileNotFound
    except ImportError as exc:
        raise AWSConnectionError(
            'Install AWS support with: pip install -e ".[aws]"'
        ) from exc
    try:
        session = boto3.Session(profile_name=profile, region_name=region)
        # Ignore environment endpoint overrides for this credential check.
        # Account identity stays in memory; neither ARN nor account ID is output.
        client = session.client(
            "sts",
            config=Config(
                connect_timeout=5,
                read_timeout=5,
                retries={"mode": "standard", "total_max_attempts": 1},
                ignore_configured_endpoint_urls=True,
            ),
        )
        try:
            client.get_caller_identity()
        finally:
            client.close()
    except ProfileNotFound as exc:
        raise AWSConnectionError(
            "AWS profile not found. Configure that named profile."
        ) from exc
    except (BotoCoreError, ClientError) as exc:
        raise AWSConnectionError(
            "AWS check failed. Verify the named profile, refresh its login, "
            "and check the region and network connection."
        ) from exc
    return {
        "status": "authenticated",
        "compute": "local",
        "message": (
            "AWS credentials accepted. Local compute remains selected. "
            "Bedrock/model access and deployment permissions have not been checked. "
            "No model invoked or resources created."
        ),
    }
