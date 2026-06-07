"""Contract and security tests for the filesystem artifact store."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from shotsight2.adapters.filesystem import ArtifactStoreRoots, FileSystemArtifactStore
from shotsight2.domain.artifacts import ArtifactId, ArtifactKind, ArtifactRoot
from shotsight2.ports.artifacts import (
    DuplicateArtifactError,
    InvalidArtifactIdError,
    UnknownArtifactError,
    UnsafeFilesystemError,
)


@pytest.fixture
def roots(tmp_path: Path) -> ArtifactStoreRoots:
    """Return isolated artifact roots."""
    return ArtifactStoreRoots.under(tmp_path / "data")


@pytest.fixture
def store(roots: ArtifactStoreRoots) -> FileSystemArtifactStore:
    """Return an artifact store backed by a temporary directory."""
    return FileSystemArtifactStore(roots)


def test_roots_and_path_policies(store: FileSystemArtifactStore, roots: ArtifactStoreRoots) -> None:
    """Configured roots and canonical identifiers should be deterministic."""
    assert all(path.is_dir() for path in (roots.uploads, roots.artifacts, roots.temporary, roots.models))
    assert store.original_id("video-1", ".MOV") == "upload:video-1/original.mov"
    assert store.proxy_id("video-1", "run-1", "proxy.mp4") == "run:video-1/run-1/proxy/proxy.mp4"
    assert store.track_id("video-1", "run-1", "ball.json") == "run:video-1/run-1/tracks/ball.json"
    assert store.replay_id("video-1", "run-1", "shot-1.mp4") == "run:video-1/run-1/replays/shot-1.mp4"
    assert store.render_id("video-1", "run-1", "tracked.mp4") == "run:video-1/run-1/rendered/tracked.mp4"
    assert store.model_id("mlx", "sam3.safetensors") == "model:mlx/sam3.safetensors"


@pytest.mark.parametrize(
    "artifact_id",
    [
        ArtifactId("/etc/passwd"),
        ArtifactId("upload:../passwd"),
        ArtifactId("upload:video/../../passwd"),
        ArtifactId("unknown:video/file"),
        ArtifactId("run:video/run/unknown/file"),
        ArtifactId("upload:video/not-original.mp4"),
        ArtifactId(r"upload:video\original.mp4"),
    ],
)
def test_rejects_absolute_traversal_and_unknown_ids(store: FileSystemArtifactStore, artifact_id: ArtifactId) -> None:
    """Logical identifiers must not bypass known path policies."""
    with pytest.raises(InvalidArtifactIdError):
        store.metadata(artifact_id)


def test_rejects_symlink_escape(store: FileSystemArtifactStore, roots: ArtifactStoreRoots, tmp_path: Path) -> None:
    """A symlink below a safe root must never redirect artifact access."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "original.mp4").write_bytes(b"private")
    roots.uploads.joinpath("video-1").symlink_to(outside, target_is_directory=True)

    with pytest.raises(UnsafeFilesystemError):
        store.metadata(store.original_id("video-1", "mp4"))


def test_temporary_resources_are_scoped_and_promoted_atomically(
    store: FileSystemArtifactStore,
) -> None:
    """Temporary files and directories should remain under their video and run."""
    temporary_file = store.create_temporary_file("video-1", "run-1", suffix=".mp4")
    temporary_directory = store.create_temporary_directory("video-1", "run-1")
    with store.open_read(temporary_file) as stream:
        assert stream.read() == b""
    assert str(temporary_file).startswith("temp:video-1/run-1/artifact-")
    assert str(temporary_directory).startswith("temp:video-1/run-1/artifact-dir-")

    destination = store.proxy_id("video-1", "run-1", "proxy.mp4")
    store.write_atomic(temporary_file, (b"video-", b"bytes"))
    promoted = store.promote(temporary_file, destination)

    assert promoted.kind is ArtifactKind.PROXY
    assert promoted.size_bytes == 11
    with store.open_read(destination) as stream:
        assert stream.read() == b"video-bytes"
    with pytest.raises(UnknownArtifactError):
        store.metadata(temporary_file)


def test_atomic_write_cleans_partial_file_after_interruption(
    store: FileSystemArtifactStore, roots: ArtifactStoreRoots
) -> None:
    """A failed publish must leave neither destination nor partial files."""
    destination = store.render_id("video-1", "run-1", "tracked.mp4")
    with patch("shotsight2.adapters.filesystem.artifact_store.os.link", side_effect=OSError("disk failure")):
        with pytest.raises(OSError, match="disk failure"):
            store.write_atomic(destination, (b"partial",))

    assert not list(roots.artifacts.rglob("*.partial"))
    with pytest.raises(UnknownArtifactError):
        store.metadata(destination)


def test_duplicate_destination_is_never_overwritten(store: FileSystemArtifactStore) -> None:
    """Completed artifact identifiers must be immutable."""
    destination = store.original_id("video-1", "mp4")
    store.write_atomic(destination, (b"first",))

    with pytest.raises(DuplicateArtifactError):
        store.write_atomic(destination, (b"second",))

    temporary = store.create_temporary_file("video-1", "run-1")
    store.write_atomic(temporary, (b"other",))
    with pytest.raises(DuplicateArtifactError):
        store.promote(temporary, destination)
    with store.open_read(destination) as stream:
        assert stream.read() == b"first"


def test_metadata_inventory_and_usage_do_not_expose_paths(
    store: FileSystemArtifactStore,
) -> None:
    """Inventory and usage should accurately describe stored logical artifacts."""
    original = store.original_id("video-1", "mov")
    replay = store.replay_id("video-1", "run-1", "shot-1.mp4")
    other = store.original_id("video-2", "mp4")
    model = store.model_id("mlx", "sam3.bin")
    store.write_atomic(original, (b"1234",))
    store.write_atomic(replay, (b"123456",))
    store.write_atomic(other, (b"x",))
    store.write_atomic(model, (b"model",))

    metadata = store.metadata(original)
    assert metadata.logical_path == "video-1/original.mov"
    assert not hasattr(metadata, "physical_path")
    assert metadata.media_type == "video/quicktime"

    inventory = store.inventory_for_video("video-1")
    assert [item.artifact_id for item in inventory.artifacts] == [original, replay]
    assert inventory.total_bytes == 10

    usage = store.storage_usage()
    assert usage.total_files == 4
    assert usage.total_bytes == 16
    assert {item.root for item in usage.roots} == set(ArtifactRoot)


def test_delete_video_tree_preserves_other_videos_and_shared_models(
    store: FileSystemArtifactStore,
) -> None:
    """Deletion must remove only the selected video's complete ownership tree."""
    selected = store.original_id("video-1", "mp4")
    selected_replay = store.replay_id("video-1", "run-1", "shot.mp4")
    other = store.original_id("video-2", "mp4")
    model = store.model_id("mlx", "shared.bin")
    for artifact_id, value in (
        (selected, b"source"),
        (selected_replay, b"replay"),
        (other, b"other"),
        (model, b"shared"),
    ):
        store.write_atomic(artifact_id, (value,))
    temporary = store.create_temporary_file("video-1", "run-1")

    deleted = store.delete_video_tree("video-1")

    assert deleted.total_bytes == 12
    for artifact_id in (selected, selected_replay, temporary):
        with pytest.raises(UnknownArtifactError):
            store.metadata(artifact_id)
    assert store.metadata(other).size_bytes == 5
    assert store.metadata(model).size_bytes == 6


def test_delete_refuses_tree_containing_symlink(
    store: FileSystemArtifactStore, roots: ArtifactStoreRoots, tmp_path: Path
) -> None:
    """Deletion must stop rather than following or silently removing a symlink."""
    original = store.original_id("video-1", "mp4")
    store.write_atomic(original, (b"source",))
    outside = tmp_path / "outside.txt"
    outside.write_text("keep")
    os.symlink(outside, roots.uploads / "video-1" / "unsafe-link")

    with pytest.raises(UnsafeFilesystemError):
        store.delete_video_tree("video-1")

    assert outside.read_text() == "keep"
    assert store.metadata(original).size_bytes == 6


def test_invalid_temporary_suffix_and_missing_artifact(store: FileSystemArtifactStore) -> None:
    """Unsafe suffixes and absent identifiers should have explicit failures."""
    with pytest.raises(InvalidArtifactIdError):
        store.create_temporary_file("video-1", "run-1", suffix="../bad")
    with pytest.raises(UnknownArtifactError):
        with store.open_read(store.original_id("missing", "mp4")):
            pass
