"""Ordinary local CLI commands remain offline and independent of
provider SDKs."""

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


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
