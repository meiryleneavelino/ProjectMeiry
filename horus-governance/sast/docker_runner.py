import json
import os
import subprocess
from pathlib import Path
from uuid import uuid4

from .contracts import AnalysisError, content_hash, normalize_code, verify_report


ROOT = Path(__file__).resolve().parents[1]
DESKTOP_DOCKER = "/Applications/Docker.app/Contents/Resources/bin/docker"
DOCKER = os.environ.get("DOCKER_BIN", DESKTOP_DOCKER if Path(DESKTOP_DOCKER).exists() else "docker")


def organizations():
    return json.loads((ROOT / "config" / "organizations.json").read_bytes())


def container_options(name):
    return ["--name", name, "--network", "none", "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges:true", "--user", "10001:10001",
            "--memory", "768m", "--memory-swap", "768m", "--cpus", "1",
            "--pids-limit", "128", "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=134217728,mode=1777"]


def docker_json(*arguments):
    result = subprocess.run([DOCKER, *arguments], capture_output=True, timeout=30, check=False)
    if result.returncode:
        raise AnalysisError("docker_unavailable", "Docker or the configured analysis image is unavailable.")
    return json.loads(result.stdout)


def build_images():
    subprocess.run([DOCKER, "build", "-f", str(ROOT / "sast" / "Dockerfile.base"),
                    "-t", "horus-sast-base:local", str(ROOT)], check=True)
    for organization, settings in organizations().items():
        subprocess.run([DOCKER, "build", "-f", str(ROOT / "sast" / "Dockerfile.organization"),
                        "--build-arg", f"ORGANIZATION={organization}",
                        "-t", settings["image"], str(ROOT)], check=True)


def analyze_in_docker(content, organization):
    code = normalize_code(content)
    settings = organizations().get(organization)
    if settings is None:
        raise AnalysisError("invalid_organization", "Unknown analysis organization.")
    image = docker_json("image", "inspect", settings["image"])[0]
    name = f"horus-sast-{uuid4().hex}"
    image_id = image["Id"]
    try:
        result = subprocess.run([DOCKER, "create", "--interactive", *container_options(name), image_id],
                                capture_output=True, timeout=30, check=False)
        if result.returncode:
            raise AnalysisError("container_failed", "The isolated analyzer could not be created.")
        try:
            result = subprocess.run([DOCKER, "start", "--attach", "--interactive", name],
                                    input=code, capture_output=True, timeout=120, check=False)
        except subprocess.TimeoutExpired:
            raise AnalysisError("analysis_timeout", "Analysis exceeded its allowed duration.") from None
        if result.returncode:
            raise AnalysisError("analysis_failed", "Analysis failed; no approval was issued.")
        try:
            envelope = json.loads(result.stdout)
            report = envelope["report"]
            if (not verify_report(report, envelope["report_hash"])
                    or report["code_hash"] != content_hash(code)
                    or envelope["provenance"]["organization"] != organization):
                raise ValueError("Invalid report")
        except (ValueError, KeyError, TypeError):
            raise AnalysisError("invalid_report", "Analysis returned an invalid report.") from None
        digests = sorted(image.get("RepoDigests") or [])
        envelope["provenance"].update({
            "image": settings["image"], "image_id": image_id,
            "repository_digests": digests,
            "digest": digests[0].split("@", 1)[1] if digests else image_id,
            "digest_kind": "repository_manifest" if digests else "docker_image_id",
        })
        return envelope
    finally:
        subprocess.run([DOCKER, "rm", "--force", name], capture_output=True, timeout=30, check=False)