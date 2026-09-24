"""AWS checks disclose no identity and remain separate from ordinary
local use."""

import json
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from labcat.aws import AWSConnectionError, check_connection
from labcat.cli import main

IDENTITY = {
    "Account": "000000000000",
    "Arn": "arn:aws:iam::000000000000:user/unit-test-private-identity",
    "UserId": "UNIT_TEST_PRIVATE_USER_ID",
}
PRIVATE_ERROR = "UNIT_TEST_PRIVATE_PROVIDER_ERROR"


@pytest.fixture
def bedrock_catalog(monkeypatch):
    import boto3

    client = Mock(spec=["list_foundation_models", "list_inference_profiles", "close"])
    client.list_foundation_models.return_value = {
        "modelSummaries": [{"modelId": "anthropic.claude-base-v1", "modelName": "Base"}]
    }
    monkeypatch.setattr(
        boto3, "Session", lambda **kw: SimpleNamespace(client=lambda *a, **k: client)
    )
    return client


def test_bedrock_profile_catalog_uses_returned_ids_for_model_verification(
    bedrock_catalog,
):
    from labcat.aws import model_options

    bedrock_catalog.list_inference_profiles.side_effect = [
        {
            "inferenceProfileSummaries": [
                {
                    "inferenceProfileId": "us.anthropic.claude-base-v1",
                    "inferenceProfileName": "US Claude",
                    "status": "ACTIVE",
                    "inferenceProfileArn": "private-account-arn",
                }
            ],
            "nextToken": "next-page",
        },
        {
            "inferenceProfileSummaries": [
                {
                    "inferenceProfileId": "us.anthropic.claude-base-v1",
                    "status": "ACTIVE",
                },
                {"inferenceProfileId": "disabled-profile", "status": "INACTIVE"},
                {"inferenceProfileId": "bad identifier", "status": "ACTIVE"},
            ]
        },
    ]
    models = model_options("test-profile", "us-west-2")
    assert {row["id"] for row in models} == {
        "us.anthropic.claude-base-v1",
        "anthropic.claude-base-v1",
    }
    assert "private-account-arn" not in json.dumps(models)
    assert bedrock_catalog.list_inference_profiles.call_args_list[1].kwargs == {
        "maxResults": 100,
        "nextToken": "next-page",
    }
    bedrock_catalog.close.assert_called_once()


def test_bedrock_profile_catalog_access_denial_preserves_foundation_catalog(
    bedrock_catalog,
):
    from botocore.exceptions import ClientError

    from labcat.aws import model_options

    bedrock_catalog.list_inference_profiles.side_effect = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": PRIVATE_ERROR}},
        "ListInferenceProfiles",
    )
    assert model_options("test-profile", "us-west-2") == [
        {"id": "anthropic.claude-base-v1", "label": "Base"}
    ]
    bedrock_catalog.close.assert_called_once()


@pytest.mark.parametrize("token", ["repeat", "bad token", 1, "x" * 2049])
def test_bedrock_profile_catalog_rejects_bad_pagination(bedrock_catalog, token):
    from labcat.aws import model_options

    bedrock_catalog.list_inference_profiles.return_value = {
        "inferenceProfileSummaries": [],
        "nextToken": token,
    }
    with pytest.raises(AWSConnectionError):
        model_options("test-profile", "us-west-2")
    assert bedrock_catalog.list_inference_profiles.call_count <= 2
    bedrock_catalog.close.assert_called_once()


def test_bedrock_profile_catalog_has_fixed_two_page_budget(bedrock_catalog):
    from labcat.aws import model_options

    bedrock_catalog.list_inference_profiles.side_effect = [
        {"inferenceProfileSummaries": [], "nextToken": "first"},
        {"inferenceProfileSummaries": [], "nextToken": "second"},
    ]
    assert len(model_options("test-profile", "us-west-2")) == 1
    assert bedrock_catalog.list_inference_profiles.call_count == 2


@pytest.mark.parametrize(
    "name",
    [
        "openai.gpt-5.5",
        "openai.gpt-5.4-high",
        "gpt-5.6-sol-xhigh",
        "google.gemma-4-31b",
    ],
)
def test_bedrock_catalog_excludes_pinned_mantle_routes(bedrock_catalog, name):
    from labcat.aws import model_options

    bedrock_catalog.list_foundation_models.return_value = {
        "modelSummaries": [{"modelId": name}]
    }
    bedrock_catalog.list_inference_profiles.return_value = {
        "inferenceProfileSummaries": []
    }
    assert model_options("test-profile", "us-west-2") == []


def test_bedrock_mantle_filter_does_not_guess_other_model_capabilities():
    from labcat.aws import requires_mantle

    assert not requires_mantle("openai.gpt-oss-120b-1:0")
    assert not requires_mantle("us.anthropic.claude-sonnet-5")
    assert not requires_mantle("future-provider.model")


@pytest.fixture
def aws_sdk(monkeypatch):
    boto3 = pytest.importorskip("boto3")
    exceptions = pytest.importorskip("botocore.exceptions")
    client = Mock(spec=["get_caller_identity", "close"])
    client.get_caller_identity.return_value = IDENTITY.copy()
    session = Mock(spec=["client"])
    session.client.return_value = client
    factory = Mock(return_value=session)
    monkeypatch.setattr(boto3, "Session", factory)
    return SimpleNamespace(
        factory=factory, session=session, client=client, exceptions=exceptions
    )


def test_identity_check_is_bounded_and_discloses_status_only(aws_sdk):
    result = check_connection("unit-test-profile", "us-west-2")

    aws_sdk.factory.assert_called_once_with(
        profile_name="unit-test-profile", region_name="us-west-2"
    )
    assert aws_sdk.session.client.call_args.args == ("sts",)
    options = aws_sdk.session.client.call_args.kwargs["config"]
    assert options.connect_timeout <= 5
    assert options.read_timeout <= 5
    assert options.retries["total_max_attempts"] == 1
    assert options.ignore_configured_endpoint_urls is True
    aws_sdk.client.get_caller_identity.assert_called_once_with()
    aws_sdk.client.close.assert_called_once_with()

    assert result["status"] == "authenticated"
    assert result["compute"] == "local"
    assert "have not been checked" in result["message"]
    assert "No model invoked or resources created" in result["message"]
    serialized = json.dumps(result)
    for private_value in IDENTITY.values():
        assert private_value not in serialized
    assert set(result) == {"status", "compute", "message"}


def test_aws_cli_success_does_not_print_identity(aws_sdk, capsys):
    assert (
        main(["aws-check", "--profile", "unit-test-profile", "--region", "us-west-2"])
        == 0
    )
    output = capsys.readouterr()
    assert not output.err
    assert json.loads(output.out)["status"] == "authenticated"
    for private_value in IDENTITY.values():
        assert private_value not in output.out


@pytest.mark.parametrize(
    ("error_name", "kwargs"),
    [
        ("NoCredentialsError", {}),
        ("UnauthorizedSSOTokenError", {}),
        ("SSOTokenLoadError", {"error_msg": PRIVATE_ERROR}),
        ("EndpointConnectionError", {"endpoint_url": PRIVATE_ERROR}),
        (
            "ClientError",
            {
                "error_response": {
                    "Error": {"Code": "ExpiredToken", "Message": PRIVATE_ERROR}
                },
                "operation_name": "GetCallerIdentity",
            },
        ),
    ],
)
def test_aws_failures_are_safe_actionable_and_close_client(aws_sdk, error_name, kwargs):
    aws_sdk.client.get_caller_identity.side_effect = getattr(
        aws_sdk.exceptions, error_name
    )(**kwargs)

    with pytest.raises(AWSConnectionError) as failure:
        check_connection("unit-test-profile", "us-west-2")
    assert "refresh its login" in str(failure.value)
    assert PRIVATE_ERROR not in str(failure.value)
    aws_sdk.client.close.assert_called_once_with()


def test_missing_named_profile_does_not_fall_back(aws_sdk):
    aws_sdk.factory.side_effect = aws_sdk.exceptions.ProfileNotFound(
        profile=PRIVATE_ERROR
    )
    with pytest.raises(AWSConnectionError, match="profile not found") as failure:
        check_connection("unit-test-profile", "us-west-2")
    assert PRIVATE_ERROR not in str(failure.value)
    aws_sdk.factory.assert_called_once()
    aws_sdk.session.client.assert_not_called()


def test_aws_cli_errors_omit_provider_details_and_traceback(aws_sdk, capsys):
    aws_sdk.client.get_caller_identity.side_effect = aws_sdk.exceptions.ClientError(
        {"Error": {"Code": "InvalidClientTokenId", "Message": PRIVATE_ERROR}},
        "GetCallerIdentity",
    )
    with pytest.raises(SystemExit) as failure:
        main(["aws-check", "--profile", "unit-test-profile", "--region", "us-west-2"])
    assert failure.value.code == 2
    output = capsys.readouterr()
    assert not output.out
    assert "AWS check failed" in output.err
    assert PRIVATE_ERROR not in output.err
    assert "Traceback" not in output.err


def test_missing_optional_sdk_has_installation_guidance(monkeypatch):
    monkeypatch.setitem(sys.modules, "boto3", None)
    with pytest.raises(AWSConnectionError, match="Install AWS support"):
        check_connection("unit-test-profile", "us-west-2")


@pytest.mark.parametrize(
    ("profile", "region"),
    [("", "us-west-2"), ("profile with spaces", "us-west-2"), ("demo", "https://host")],
)
def test_invalid_connection_inputs_fail_before_loading_optional_sdk(
    monkeypatch, profile, region
):
    monkeypatch.setitem(sys.modules, "boto3", None)
    with pytest.raises(AWSConnectionError) as failure:
        check_connection(profile, region)
    assert "Install AWS support" not in str(failure.value)


@pytest.mark.parametrize(
    "arguments", [["status"], ["status", "--format", "json"], ["check-config"]]
)
def test_fresh_local_cli_never_imports_aws_or_accesses_network(tmp_path, arguments):
    script = textwrap.dedent("""
        import importlib.abc
        import json
        import sys

        attempts = []

        class BlockAWS(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname.split('.')[0] in {'boto3', 'botocore'} or (
                    fullname == 'labcat.aws'
                ):
                    attempts.append(fullname)
                    raise AssertionError('Ordinary local CLI attempted an AWS import')

        def block_network(event, args):
            if event.startswith('socket.'):
                attempts.append(event)
                raise AssertionError('Ordinary local CLI attempted network access')

        sys.meta_path.insert(0, BlockAWS())
        sys.addaudithook(block_network)
        sys.path.insert(0, sys.argv[1])
        from labcat.cli import main
        assert main(json.loads(sys.argv[2])) == 0
        assert not attempts
        loaded_packages = {name.split('.')[0] for name in sys.modules}
        assert not loaded_packages.intersection({'boto3', 'botocore'})
        """)
    source = Path(__file__).resolve().parents[1] / "src"
    result = subprocess.run(
        [sys.executable, "-I", "-c", script, str(source), json.dumps(arguments)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout
    assert not result.stderr
