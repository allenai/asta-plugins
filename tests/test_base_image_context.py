"""Exercise registry fallback without network access or registry credentials."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DIGEST = "sha256:" + "a" * 64
REF = "public.ecr.aws/docker/library/node:22-slim"


@pytest.mark.skipif(
    not shutil.which("bash") or not shutil.which("jq"), reason="requires bash and jq"
)
@pytest.mark.parametrize(
    ("ecr_digest", "hub_digest", "mirror_available", "source"),
    [
        (DIGEST, DIGEST, True, "mirror.gcr.io/library/node"),
        (DIGEST, DIGEST, False, "public.ecr.aws/docker/library/node"),
        (None, DIGEST, True, "mirror.gcr.io/library/node"),
        (None, DIGEST, False, "docker.io/library/node"),
        ("invalid-digest", DIGEST, False, "docker.io/library/node"),
        (None, None, True, None),
        (None, "invalid-digest", True, None),
    ],
    ids=[
        "ecr-mirror-hit",
        "ecr-mirror-miss",
        "hub-mirror-hit",
        "hub-mirror-miss",
        "invalid-ecr-digest",
        "publishers-unavailable",
        "invalid-hub-digest",
    ],
)
def test_base_image_uses_mirror_or_publisher_that_resolved_digest(
    tmp_path, ecr_digest, hub_digest, mirror_available, source
):
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(f"FROM {REF} AS asta\n")
    requests = tmp_path / "requests.jsonl"
    config = tmp_path / "registry.json"
    config.write_text(
        json.dumps(
            {
                "public.ecr.aws": ecr_digest,
                "registry-1.docker.io": hub_digest,
                "mirror.gcr.io": DIGEST if mirror_available else None,
            }
        )
    )
    curl = tmp_path / "curl"
    curl.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "from urllib.parse import urlsplit\n"
        "url = sys.argv[-1]\n"
        "with open(os.environ['REQUESTS'], 'a') as log:\n"
        "    log.write(json.dumps(url) + '\\n')\n"
        "if '/token' in url:\n"
        "    print(json.dumps({'token': 'test-token'}))\n"
        "    sys.exit(0)\n"
        "with open(os.environ['REGISTRIES']) as config:\n"
        "    digest = json.load(config)[urlsplit(url).netloc]\n"
        "if digest is None:\n"
        "    print('registry request failed', file=sys.stderr)\n"
        "    sys.exit(22)\n"
        "print('HTTP/2 200\\r')\n"
        "print('Docker-Content-Digest: ' + digest + '\\r')\n"
    )
    curl.chmod(0o755)
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/base-image-context.sh"), str(dockerfile)],
        env={
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "REQUESTS": str(requests),
            "REGISTRIES": str(config),
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    urls = [json.loads(line) for line in requests.read_text().splitlines()]
    if source is None:
        assert result.returncode != 0
        assert result.stdout == ""
        assert "could not resolve" in result.stderr
        assert not any("mirror.gcr.io" in url for url in urls)
        return

    assert result.returncode == 0, result.stderr
    assert result.stdout == f"{REF}=docker-image://{source}@{DIGEST}\n"
    assert f"https://mirror.gcr.io/v2/library/node/manifests/{DIGEST}" in urls
    assert any("registry-1.docker.io" in url for url in urls) == (ecr_digest != DIGEST)
    if not mirror_available:
        assert f"pulling it from {source}" in result.stderr
