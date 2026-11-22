"""Which image a container runs, read from ``docker inspect`` output, and whether the build's server is that container."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

SNAPSHOT_DIR = Path(__file__).resolve().parents[1] / "snapshot"


@pytest.fixture(scope="module")
def modules():
    sys.path.insert(0, str(SNAPSHOT_DIR))
    try:
        import build
        import image

        yield types.SimpleNamespace(build=build, image=image)
    finally:
        sys.path.remove(str(SNAPSHOT_DIR))


def _image_document(image_id: str, repo_digests: list[str], arch: str = "amd64") -> dict:
    """The shape ``docker image inspect --format '{{json .}}'`` prints (fields the code reads, and a few more)."""
    return {
        "Id": image_id,
        "RepoTags": ["laxzal/tckdb-api:0.4.0"] if repo_digests else [],
        "RepoDigests": repo_digests,
        "Os": "linux",
        "Architecture": arch,
        "Config": {"Entrypoint": ["/usr/local/bin/_entrypoint.sh"], "WorkingDir": "/app/backend"},
        "Size": 459728389,
    }


def _fake_docker(monkeypatch, image, *, container_image_id: str, document: dict | None, args: list[str] | None = None):
    def run(argv, **_):
        if argv[:2] == ["docker", "inspect"] and "{{.State.Running}}" in argv:
            return types.SimpleNamespace(returncode=0, stdout="true\n", stderr="")
        if argv[:2] == ["docker", "inspect"] and "{{.Image}}" in argv:
            return types.SimpleNamespace(returncode=0, stdout=container_image_id + "\n", stderr="")
        if argv[:2] == ["docker", "inspect"] and "{{json .Args}}" in argv:
            return types.SimpleNamespace(returncode=0, stdout=json.dumps(args or []) + "\n", stderr="")
        if argv[:3] == ["docker", "image", "inspect"]:
            if document is None:
                return types.SimpleNamespace(returncode=1, stdout="", stderr="Error: No such image")
            return types.SimpleNamespace(returncode=0, stdout=json.dumps(document) + "\n", stderr="")
        raise AssertionError(f"unexpected command {argv}")

    monkeypatch.setattr(image.subprocess, "run", run)


def test_the_pinned_index_digest_in_repo_digests_is_pinned(modules, monkeypatch):
    image = modules.image
    pinned = image.PINS["tckdb"]["image_digest"]
    _fake_docker(monkeypatch, image, container_image_id=pinned,
                 document=_image_document(pinned, [f"laxzal/tckdb-api@{pinned}"]))
    assert image.container_image("c")["pinned_as"] == f"index {pinned}"


def test_another_repo_digest_is_not_pinned(modules, monkeypatch):
    image = modules.image
    other = "sha256:" + "1" * 64
    _fake_docker(monkeypatch, image, container_image_id=other, document=_image_document(other, [f"laxzal/tckdb-api@{other}"]))
    found = image.container_image("c")
    assert found["pinned_as"] is None and found["id"] == other


def test_empty_repo_digests_and_an_unknown_id_are_not_pinned(modules, monkeypatch):
    image = modules.image
    other = "sha256:" + "2" * 64
    _fake_docker(monkeypatch, image, container_image_id=other, document=_image_document(other, []))
    assert image.container_image("c")["pinned_as"] is None


def test_a_config_id_alone_is_pinned_for_its_platform_only(modules, monkeypatch):
    image = modules.image
    config = image.PLATFORMS["linux/amd64"]["config"]
    _fake_docker(monkeypatch, image, container_image_id=config, document=_image_document(config, []))
    assert image.container_image("c")["pinned_as"] == f"linux/amd64 config {config}"
    _fake_docker(monkeypatch, image, container_image_id=config, document=_image_document(config, [], arch="arm64"))
    assert image.container_image("c")["pinned_as"] is None


def test_a_loaded_platform_manifest_is_pinned(modules, monkeypatch):
    image = modules.image
    manifest = image.PLATFORMS["linux/amd64"]["manifest"]
    _fake_docker(monkeypatch, image, container_image_id=manifest,
                 document=_image_document(manifest, [f"laxzal/tckdb-api@{manifest}"]))
    assert image.container_image("c")["pinned_as"] == f"linux/amd64 manifest {manifest}"


def test_an_image_that_cannot_be_inspected_is_not_pinned(modules, monkeypatch):
    image = modules.image
    _fake_docker(monkeypatch, image, container_image_id="sha256:" + "3" * 64, document=None)
    assert image.container_image("c")["pinned_as"] is None


def test_a_container_running_another_image_is_refused(modules, monkeypatch):
    build, image = modules.build, modules.image
    other = "sha256:" + "4" * 64
    _fake_docker(monkeypatch, image, container_image_id=other, document=_image_document(other, []))
    (problem,) = build.image_problems("tckdb-snapshot-x")  # build and image share the subprocess module
    assert problem.startswith(f"the API container tckdb-snapshot-x runs {other}, not the image pins.toml names")


def test_the_server_must_be_the_containers_port_and_the_pinned_revision(modules, monkeypatch):
    build = modules.build
    args = ["uvicorn", "app.api.app:create_app", "--factory", "--host", "127.0.0.1", "--port", "8185"]

    def run(argv, **_):
        assert "{{json .Args}}" in argv
        return types.SimpleNamespace(returncode=0, stdout=json.dumps(args), stderr="")

    monkeypatch.setattr(build.subprocess, "run", run)
    assert build.served_by_problems("c", "http://127.0.0.1:8185", "rev1", "rev1") == []
    (port,) = build.served_by_problems("c", "http://127.0.0.1:8184", "rev1", "rev1")
    assert "does not serve port 8184" in port
    (host,) = build.served_by_problems("c", "http://10.0.0.5:8185", "rev1", "rev1")
    assert "not a loopback address" in host
    (revision,) = build.served_by_problems("c", "http://localhost:8185", "rev0", "rev1")
    assert "reports database revision rev0" in revision
    assert len(build.served_by_problems("c", "http://127.0.0.1:8185", "rev1", None)) == 1


_ATTESTATION = {
    "mediaType": "application/vnd.oci.image.manifest.v1+json", "digest": "sha256:" + "a" * 64,
    "annotations": {"io.containerd.manifest.subject": "sha256:" + "7" * 64},
    "artifactType": "application/vnd.docker.attestation.manifest.v1+json",
}


@pytest.mark.parametrize("platform_field", [True, False])  # saved from a pulled index, and from a loaded image
def test_the_saved_file_names_one_tagged_platform_image(modules, platform_field):
    image = modules.image
    pinned = image.PLATFORMS["linux/amd64"]
    entry = {"mediaType": "application/vnd.oci.image.manifest.v1+json", "digest": pinned["manifest"]}
    if platform_field:
        entry["platform"] = {"architecture": "amd64", "os": "linux"}
    index = {"manifests": [entry, _ATTESTATION]}
    manifest = [{"Config": "blobs/sha256/" + pinned["config"].split(":")[1], "RepoTags": [image.VERSION_TAG]}]
    assert image.saved_image(index, manifest) == {
        "tag": image.VERSION_TAG, "manifest": pinned["manifest"], "config": pinned["config"]
    }


def test_an_untagged_or_index_only_save_is_not_one_image(modules):
    image = modules.image
    index_only = {"manifests": [{"mediaType": "application/vnd.oci.image.index.v1+json", "digest": "sha256:" + "5" * 64}]}
    untagged = [{"Config": "blobs/sha256/" + "6" * 64, "RepoTags": None}]
    assert image.saved_image(index_only, untagged) is None
