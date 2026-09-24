"""The CLI reports available software without placeholder science."""

import json

import pytest

from labcat.cli import main
from labcat.config import load_config
from labcat.service import get_status, render_text


@pytest.mark.parametrize("style", ["pi", "audit"])
def test_cli_json_uses_shared_status_without_placeholder_materials(capsys, style):
    assert main(["status", "--style", style, "--format", "json"]) == 0
    output = capsys.readouterr()
    report = json.loads(output.out)

    assert not output.err
    assert report == get_status(load_config(), style)
    assert report["candidates"] == []
    assert report["stage"] == "scaffold"
    assert "The research command and UI are not available yet." in report["message"]
    assert any(
        "Status contains no scientific records" in item
        for item in report["limitations"]
    )


def test_cli_default_text_and_configured_audit_presentation(tmp_path, capsys):
    assert main(["status"]) == 0
    assert capsys.readouterr().out == render_text(get_status(load_config()))

    config_path = tmp_path / "preferences.toml"
    config_path.write_text(
        '[presentation]\nstyle = "audit"\nterminology = "technical"\n',
        encoding="utf-8",
    )
    assert main(["--config", str(config_path), "status"]) == 0
    text = capsys.readouterr().out
    assert "Evidence policy:" in text
    assert "Configuration (preferences only):" in text
    assert text == render_text(get_status(load_config(config_path)), "technical")


@pytest.mark.parametrize(
    "args",
    [
        ["status", "--style", "unrecognized"],
        ["search", "invent scientific evidence"],
        ["serve", "--port", "0"],
    ],
)
def test_cli_invalid_requests_exit_nonzero(args, capsys):
    with pytest.raises(SystemExit) as error:
        main(args)
    assert error.value.code == 2
    output = capsys.readouterr()
    assert "error:" in output.err
    assert not output.out


@pytest.mark.parametrize("config_text", [None, "[ranking", "[policy]\noverride = true"])
def test_cli_configuration_errors_are_actionable(tmp_path, capsys, config_text):
    path = tmp_path / "preferences.toml"
    if config_text is not None:
        path.write_text(config_text, encoding="utf-8")
    with pytest.raises(SystemExit) as error:
        main(["--config", str(path), "check-config"])
    assert error.value.code == 2
    assert "Configuration error:" in capsys.readouterr().err
