import argparse
import os
import subprocess
import sys
from pathlib import Path

from sast.contracts import AnalysisError, MAX_CODE_BYTES, canonical_json, validate_filename
from sast.docker_runner import analyze_in_docker, build_images, organizations
from sast.docker_runner import DOCKER, ROOT


def main():
    parser = argparse.ArgumentParser(description="Build and test isolated Horus static analyzers; never execute submitted code.")
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("build")
    for action in ("start", "stop", "status"):
        actions.add_parser(action)
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
        if arguments.action in ("start", "stop", "status"):
            from app.settings import Settings
            if arguments.action == "start" and not (ROOT.parent / "configuration/federated-training/.local/api-token").is_file():
                raise AnalysisError("training_credentials_missing", "Start the existing training setup before governance; its token is only read, never created here.")
            Settings.load().token()
            environment = dict(os.environ, HORUS_UID=str(os.getuid()), HORUS_GID=str(os.getgid()))
            if os.uname().sysname != "Darwin" and Path("/var/run/docker.sock").exists():
                environment.setdefault("HORUS_DOCKER_GID", str(Path("/var/run/docker.sock").stat().st_gid))
            commands = {"start": ["up", "--build", "--detach", "--wait"], "stop": ["down"], "status": ["ps"]}
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