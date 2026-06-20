"""Secure filesystem implementation of the artifact-store port."""

from __future__ import annotations

import mimetypes
import os
import re
import shutil
import tempfile
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO
from uuid import uuid4

from shotsight2.domain.artifacts import (
    ArtifactId,
    ArtifactInventory,
    ArtifactKind,
    ArtifactMetadata,
    ArtifactRoot,
    RootUsage,
    StorageUsage,
)
from shotsight2.ports.artifacts import (
    DuplicateArtifactError,
    InvalidArtifactIdError,
    UnknownArtifactError,
    UnsafeFilesystemError,
)

_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_RUN_DIRECTORIES: dict[ArtifactKind, str] = {
    ArtifactKind.PROXY: "proxy",
    ArtifactKind.CALIBRATION: "calibration",
    ArtifactKind.TRACK: "tracks",
    ArtifactKind.REPLAY: "replays",
    ArtifactKind.RENDER: "rendered",
    ArtifactKind.REPORT: "reports",
}
_DIRECTORY_KINDS = {value: key for key, value in _RUN_DIRECTORIES.items()}


@dataclass(frozen=True, slots=True)
class ArtifactStoreRoots:
    """Configured physical roots owned by the artifact store."""

    uploads: Path
    artifacts: Path
    temporary: Path
    models: Path

    @classmethod
    def under(cls, data_dir: Path) -> ArtifactStoreRoots:
        """Build the standard root layout below an application data directory."""
        return cls(
            uploads=data_dir / "uploads",
            artifacts=data_dir / "artifacts",
            temporary=data_dir / "temporary",
            models=data_dir / "models",
        )


@dataclass(frozen=True, slots=True)
class _ParsedArtifact:
    root: ArtifactRoot
    kind: ArtifactKind
    parts: tuple[str, ...]


class FileSystemArtifactStore:
    """Store local artifacts while enforcing logical-path security boundaries."""

    def __init__(self, roots: ArtifactStoreRoots) -> None:
        self._roots = roots
        configured_paths = {
            ArtifactRoot.UPLOAD: roots.uploads,
            ArtifactRoot.RUN: roots.artifacts,
            ArtifactRoot.TEMP: roots.temporary,
            ArtifactRoot.MODEL: roots.models,
        }
        self._root_paths = {name: path.expanduser().absolute() for name, path in configured_paths.items()}
        self._create_roots()

    def original_id(self, video_id: str, extension: str) -> ArtifactId:
        """Return the canonical original-video identifier."""
        normalized_extension = extension.lstrip(".").lower()
        self._validate_component(video_id)
        self._validate_component(normalized_extension)
        return ArtifactId(f"upload:{video_id}/original.{normalized_extension}")

    def proxy_id(self, video_id: str, run_id: str, filename: str) -> ArtifactId:
        """Return an analysis proxy identifier."""
        return self._run_id(ArtifactKind.PROXY, video_id, run_id, filename)

    def track_id(self, video_id: str, run_id: str, filename: str) -> ArtifactId:
        """Return a track-data identifier."""
        return self._run_id(ArtifactKind.TRACK, video_id, run_id, filename)

    def replay_id(self, video_id: str, run_id: str, filename: str) -> ArtifactId:
        """Return a replay-video identifier."""
        return self._run_id(ArtifactKind.REPLAY, video_id, run_id, filename)

    def render_id(self, video_id: str, run_id: str, filename: str) -> ArtifactId:
        """Return a rendered-output identifier."""
        return self._run_id(ArtifactKind.RENDER, video_id, run_id, filename)

    def model_id(self, backend: str, filename: str) -> ArtifactId:
        """Return a shared model identifier."""
        self._validate_components((backend, filename))
        return ArtifactId(f"model:{backend}/{filename}")

    def create_temporary_file(self, video_id: str, run_id: str, *, suffix: str = "") -> ArtifactId:
        """Create an empty temporary file scoped to a video and run."""
        self._validate_components((video_id, run_id))
        self._validate_suffix(suffix)
        parent = self._resolve_parts(ArtifactRoot.TEMP, (video_id, run_id), require_exists=False)
        parent.mkdir(parents=True, exist_ok=True)
        self._assert_safe_path(parent)
        descriptor, raw_path = tempfile.mkstemp(prefix="artifact-", suffix=suffix, dir=parent)
        os.close(descriptor)
        path = Path(raw_path)
        return ArtifactId(f"temp:{video_id}/{run_id}/{path.name}")

    def create_temporary_directory(self, video_id: str, run_id: str) -> ArtifactId:
        """Create a temporary directory scoped to a video and run."""
        self._validate_components((video_id, run_id))
        parent = self._resolve_parts(ArtifactRoot.TEMP, (video_id, run_id), require_exists=False)
        parent.mkdir(parents=True, exist_ok=True)
        self._assert_safe_path(parent)
        path = Path(tempfile.mkdtemp(prefix="artifact-dir-", dir=parent))
        return ArtifactId(f"temp:{video_id}/{run_id}/{path.name}")

    def write_atomic(self, artifact_id: ArtifactId, chunks: Iterable[bytes]) -> ArtifactMetadata:
        """Write bytes to a sibling temporary file, then atomically publish them."""
        parsed = self._parse(artifact_id)
        destination = self._resolve(artifact_id, require_exists=False)
        if destination.exists() and parsed.kind is not ArtifactKind.TEMPORARY:
            raise DuplicateArtifactError(f"Artifact already exists: {artifact_id}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._assert_safe_path(destination.parent)
        partial = destination.with_name(f".{destination.name}.{uuid4().hex}.partial")
        try:
            with partial.open("xb") as output:
                for chunk in chunks:
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            if parsed.kind is ArtifactKind.TEMPORARY:
                os.replace(partial, destination)
            else:
                self._publish_no_replace(partial, destination)
        except BaseException:
            partial.unlink(missing_ok=True)
            raise
        return self.metadata(artifact_id)

    def promote(self, temporary_id: ArtifactId, destination_id: ArtifactId) -> ArtifactMetadata:
        """Atomically move a temporary file to a permanent identifier."""
        temporary = self._parse(temporary_id)
        destination = self._parse(destination_id)
        if temporary.kind is not ArtifactKind.TEMPORARY:
            raise InvalidArtifactIdError("Promotion source must be a temporary artifact")
        if destination.kind is ArtifactKind.TEMPORARY:
            raise InvalidArtifactIdError("Promotion destination must be permanent")
        source_path = self._resolve(temporary_id, require_exists=True)
        if not source_path.is_file():
            raise InvalidArtifactIdError("Promotion source must be a regular file")
        destination_path = self._resolve(destination_id, require_exists=False)
        if destination_path.exists():
            raise DuplicateArtifactError(f"Artifact already exists: {destination_id}")
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        self._assert_safe_path(destination_path.parent)
        self._publish_no_replace(source_path, destination_path)
        return self.metadata(destination_id)

    @contextmanager
    def open_read(self, artifact_id: ArtifactId) -> Iterator[BinaryIO]:
        """Open an existing regular file without returning its physical path."""
        path = self._resolve(artifact_id, require_exists=True)
        if not path.is_file():
            raise UnknownArtifactError(f"Artifact is not a file: {artifact_id}")
        with path.open("rb") as stream:
            yield stream

    @contextmanager
    def local_path(self, artifact_id: ArtifactId) -> Iterator[Path]:
        """Yield a validated path for trusted subprocess-based adapters."""
        path = self._resolve(artifact_id, require_exists=True)
        if not path.is_file():
            raise UnknownArtifactError(f"Artifact is not a file: {artifact_id}")
        yield path

    def metadata(self, artifact_id: ArtifactId) -> ArtifactMetadata:
        """Return safe metadata for an existing regular file."""
        parsed = self._parse(artifact_id)
        path = self._resolve(artifact_id, require_exists=True)
        if not path.is_file():
            raise UnknownArtifactError(f"Artifact is not a file: {artifact_id}")
        return self._metadata_for(artifact_id, parsed.kind, path)

    def inventory_for_video(self, video_id: str) -> ArtifactInventory:
        """Scan permanent roots for files owned by one video."""
        self._validate_component(video_id)
        records: list[ArtifactMetadata] = []
        upload_tree = self._resolve_parts(ArtifactRoot.UPLOAD, (video_id,), require_exists=False)
        run_tree = self._resolve_parts(ArtifactRoot.RUN, (video_id,), require_exists=False)
        records.extend(self._inventory_tree(ArtifactRoot.UPLOAD, upload_tree))
        records.extend(self._inventory_tree(ArtifactRoot.RUN, run_tree))
        ordered = tuple(records)
        return ArtifactInventory(
            video_id=video_id,
            artifacts=ordered,
            total_bytes=sum(item.size_bytes for item in ordered),
        )

    def storage_usage(self) -> StorageUsage:
        """Calculate usage without following symlinks."""
        usages: list[RootUsage] = []
        for root_name, root_path in self._root_paths.items():
            file_count = 0
            size_bytes = 0
            for path in self._walk_files(root_path):
                file_count += 1
                size_bytes += path.stat(follow_symlinks=False).st_size
            usages.append(RootUsage(root=root_name, file_count=file_count, size_bytes=size_bytes))
        return StorageUsage(
            roots=tuple(usages),
            total_files=sum(item.file_count for item in usages),
            total_bytes=sum(item.size_bytes for item in usages),
        )

    def delete_video_tree(self, video_id: str) -> ArtifactInventory:
        """Delete uploads, run artifacts, and temporary data owned by one video."""
        inventory = self.inventory_for_video(video_id)
        for root_name in (ArtifactRoot.UPLOAD, ArtifactRoot.RUN, ArtifactRoot.TEMP):
            tree = self._resolve_parts(root_name, (video_id,), require_exists=False)
            if tree.exists():
                self._assert_tree_has_no_symlinks(tree)
                shutil.rmtree(tree)
        return inventory

    def clean_run_working_files(
        self,
        video_id: str,
        run_id: str,
        *,
        preserve_diagnostics: bool,
    ) -> None:
        """Clean temporaries and compensate outputs from an unpublished run.

        Successful runs retain their published tree. Failed runs also remove
        promoted outputs, while an existing reports directory may remain for
        diagnostics.
        """

        self._validate_components((video_id, run_id))
        temporary = self._resolve_parts(ArtifactRoot.TEMP, (video_id, run_id), require_exists=False)
        if temporary.exists():
            self._assert_tree_has_no_symlinks(temporary)
            shutil.rmtree(temporary)
        if not preserve_diagnostics:
            return

        permanent = self._resolve_parts(ArtifactRoot.RUN, (video_id, run_id), require_exists=False)
        if not permanent.exists():
            return
        self._assert_tree_has_no_symlinks(permanent)
        for child in permanent.iterdir():
            if child.name == _RUN_DIRECTORIES[ArtifactKind.REPORT]:
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        if not any(permanent.iterdir()):
            permanent.rmdir()

    def _run_id(self, kind: ArtifactKind, video_id: str, run_id: str, filename: str) -> ArtifactId:
        directory = _RUN_DIRECTORIES[kind]
        self._validate_components((video_id, run_id, filename))
        return ArtifactId(f"run:{video_id}/{run_id}/{directory}/{filename}")

    def _create_roots(self) -> None:
        for root in self._root_paths.values():
            if root.is_symlink():
                raise UnsafeFilesystemError(f"Artifact root cannot be a symlink: {root}")
            root.mkdir(parents=True, exist_ok=True)
            if not root.is_dir():
                raise UnsafeFilesystemError(f"Artifact root is not a directory: {root}")
        resolved_roots = [root.resolve(strict=True) for root in self._root_paths.values()]
        if len(set(resolved_roots)) != len(resolved_roots):
            raise UnsafeFilesystemError("Artifact roots must resolve to distinct directories")
        for root in resolved_roots:
            if any(root.is_relative_to(other) for other in resolved_roots if other != root):
                raise UnsafeFilesystemError("Artifact roots must not be nested")
        self._root_paths = dict(zip(self._root_paths, resolved_roots, strict=True))

    def _parse(self, artifact_id: ArtifactId) -> _ParsedArtifact:
        raw = str(artifact_id)
        if not raw or raw.startswith(("/", "\\")):
            raise InvalidArtifactIdError("Artifact identifier must be logical and relative")
        prefix, separator, logical_path = raw.partition(":")
        if not separator or not logical_path:
            raise InvalidArtifactIdError("Artifact identifier must include a known root")
        try:
            root = ArtifactRoot(prefix)
        except ValueError as error:
            raise InvalidArtifactIdError(f"Unknown artifact root: {prefix}") from error
        pure_path = PurePosixPath(logical_path)
        parts = pure_path.parts
        if pure_path.is_absolute() or not parts:
            raise InvalidArtifactIdError("Artifact path must be relative")
        self._validate_components(parts)
        kind = self._kind_for(root, parts)
        return _ParsedArtifact(root=root, kind=kind, parts=parts)

    def _kind_for(self, root: ArtifactRoot, parts: tuple[str, ...]) -> ArtifactKind:
        if root is ArtifactRoot.UPLOAD and len(parts) == 2 and parts[1].startswith("original."):
            return ArtifactKind.ORIGINAL
        if root is ArtifactRoot.RUN and len(parts) == 4:
            try:
                return _DIRECTORY_KINDS[parts[2]]
            except KeyError as error:
                raise InvalidArtifactIdError(f"Unknown run artifact kind: {parts[2]}") from error
        if root is ArtifactRoot.TEMP and len(parts) >= 3:
            return ArtifactKind.TEMPORARY
        if root is ArtifactRoot.MODEL and len(parts) == 2:
            return ArtifactKind.MODEL
        raise InvalidArtifactIdError("Artifact identifier does not match a supported path policy")

    def _resolve(self, artifact_id: ArtifactId, *, require_exists: bool) -> Path:
        parsed = self._parse(artifact_id)
        return self._resolve_parts(parsed.root, parsed.parts, require_exists=require_exists)

    def _resolve_parts(self, root_name: ArtifactRoot, parts: tuple[str, ...], *, require_exists: bool) -> Path:
        root = self._root_paths[root_name]
        path = root.joinpath(*parts)
        self._assert_safe_path(path)
        if require_exists and not path.exists():
            raise UnknownArtifactError("Artifact does not exist")
        return path

    def _assert_safe_path(self, path: Path) -> None:
        for candidate in (path, *path.parents):
            if candidate == self._root_paths.get(ArtifactRoot.UPLOAD):
                break
            if candidate.is_symlink():
                raise UnsafeFilesystemError("Artifact path contains a symlink")
        matching_roots = [root for root in self._root_paths.values() if path.is_relative_to(root)]
        if len(matching_roots) != 1:
            raise UnsafeFilesystemError("Artifact path escapes its configured root")
        root = matching_roots[0]
        relative = path.relative_to(root)
        candidate = root
        if root.is_symlink():
            raise UnsafeFilesystemError("Artifact root cannot be a symlink")
        for part in relative.parts:
            candidate /= part
            if candidate.is_symlink():
                raise UnsafeFilesystemError("Artifact path contains a symlink")

    def _inventory_tree(self, root_name: ArtifactRoot, tree: Path) -> list[ArtifactMetadata]:
        if not tree.exists():
            return []
        records: list[ArtifactMetadata] = []
        root = self._root_paths[root_name]
        for path in self._walk_files(tree):
            logical = "/".join(path.relative_to(root).parts)
            artifact_id = ArtifactId(f"{root_name.value}:{logical}")
            parsed = self._parse(artifact_id)
            records.append(self._metadata_for(artifact_id, parsed.kind, path))
        return records

    def _walk_files(self, tree: Path) -> Iterator[Path]:
        if not tree.exists():
            return
        self._assert_tree_has_no_symlinks(tree)
        for directory, directory_names, filenames in os.walk(tree, followlinks=False):
            directory_path = Path(directory)
            directory_names.sort()
            filenames.sort()
            for filename in filenames:
                path = directory_path / filename
                if path.is_symlink():
                    raise UnsafeFilesystemError("Artifact tree contains a symlink")
                if path.is_file():
                    yield path

    def _assert_tree_has_no_symlinks(self, tree: Path) -> None:
        self._assert_safe_path(tree)
        for directory, directory_names, filenames in os.walk(tree, followlinks=False):
            directory_path = Path(directory)
            for name in (*directory_names, *filenames):
                if (directory_path / name).is_symlink():
                    raise UnsafeFilesystemError("Artifact tree contains a symlink")

    @staticmethod
    def _publish_no_replace(source: Path, destination: Path) -> None:
        """Atomically publish a complete file while refusing an existing target."""
        try:
            os.link(source, destination)
        except FileExistsError as error:
            raise DuplicateArtifactError(f"Artifact already exists: {destination.name}") from error
        source.unlink(missing_ok=True)

    @staticmethod
    def _metadata_for(artifact_id: ArtifactId, kind: ArtifactKind, path: Path) -> ArtifactMetadata:
        media_type, _ = mimetypes.guess_type(path.name)
        return ArtifactMetadata(
            artifact_id=artifact_id,
            kind=kind,
            logical_path=str(artifact_id).partition(":")[2],
            size_bytes=path.stat(follow_symlinks=False).st_size,
            media_type=media_type,
        )

    @staticmethod
    def _validate_components(parts: tuple[str, ...]) -> None:
        for part in parts:
            FileSystemArtifactStore._validate_component(part)

    @staticmethod
    def _validate_component(component: str) -> None:
        if component in {"", ".", ".."} or not _SAFE_COMPONENT.fullmatch(component):
            raise InvalidArtifactIdError(f"Unsafe artifact path component: {component!r}")

    @staticmethod
    def _validate_suffix(suffix: str) -> None:
        if suffix and (not suffix.startswith(".") or not _SAFE_COMPONENT.fullmatch(suffix[1:])):
            raise InvalidArtifactIdError(f"Unsafe temporary suffix: {suffix!r}")
