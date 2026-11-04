import argparse
import os
import subprocess
import sys
from pathlib import Path

from sast.contracts import AnalysisError, MAX_CODE_BYTES, canonical_json, validate_filename
from sast.docker_runner import analyze_in_docker, build_images, organizations
from sast.docker_runner import DOCKER, ROOT


def main():
    parser = argparse.ArgumentParser(description="Horus governance: analyzer images, the Fabric ledger and the API. Submitted code is never executed.")
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("build")
    for action in ("start", "stop", "status"):
        actions.add_parser(action)
    ledger = actions.add_parser("ledger", help="Hyperledger Fabric governance ledger in the kind cluster")
    ledger.add_argument("ledger_action", choices=("setup", "status", "verify", "forward", "down"))
    ledger.add_argument("--skip-build", action="store_true", help="setup: reuse already built images")
    ledger.add_argument("--background", action="store_true", help="forward: keep running detached")
    ledger.add_argument("--purge", action="store_true", help="down: also delete ledger data and identities")
    analyze = actions.add_parser("analyze")
    analyze.add_argument("--organization", choices=tuple(organizations()), required=True)
    source = analyze.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", type=Path)
    source.add_argument("--stdin", action="store_true")
    arguments = parser.parse_args()
    try:
        if arguments.action == "build":
            build_images()
            return 0
        if arguments.action == "ledger":
            from deploy.ledger import setup as ledger_setup
            action = arguments.ledger_action
            if action == "setup":
                ledger_setup.setup(arguments.skip_build)
            elif action == "verify":
                return 0 if ledger_setup.verify() else 1
            elif action == "forward":
                ledger_setup.forward(arguments.background)
            elif action == "down":
                ledger_setup.down(arguments.purge)
            else:
                ledger_setup.status()
            return 0
        if arguments.action in ("start", "stop", "status"):
            from app.settings import Settings
            if arguments.action == "start" and not (ROOT.parent / "configuration/federated-training/.local/api-token").is_file():
                raise AnalysisError("training_credentials_missing", "Start the existing training setup before governance; its token is only read, never created here.")
            if arguments.action == "start" and not (ROOT / ".local/ledger/gateway-token").is_file():
                raise AnalysisError("ledger_missing", "Run 'python3 tools.py ledger setup' first; governance history lives on the Fabric ledger.")
            Settings.load().token()
            environment = dict(os.environ, HORUS_UID=str(os.getuid()), HORUS_GID=str(os.getgid()))
            commands = {"start": ["up", "--build", "--detach", "--wait", "--remove-orphans"], "stop": ["down", "--remove-orphans"], "status": ["ps"]}
            subprocess.run([DOCKER, "compose", "-f", str(ROOT / "compose.yaml"), *commands[arguments.action]],
                           env=environment, check=True)
            return 0
        if arguments.file is not None:
            validate_filename(arguments.file.name)
            with arguments.file.open("rb") as source_file:
                content = source_file.read(MAX_CODE_BYTES + 1)
        else:
            content = sys.stdin.buffer.read(MAX_CODE_BYTES + 1)
        envelope = analyze_in_docker(content, arguments.organization)
        sys.stdout.buffer.write(canonical_json(envelope) + b"\n")
        return 0
    except AnalysisError as error:
        sys.stderr.buffer.write(canonical_json({"error": {"code": error.code, "message": str(error)}}) + b"\n")
        return 2
    except (OSError, ValueError):
        sys.stderr.write("Input or analyzer configuration is unavailable; no approval was issued.\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())