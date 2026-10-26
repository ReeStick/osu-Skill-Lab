"""Small non-executable JSON artifacts, addressed only by server-generated UUID."""

import hashlib
from pathlib import Path
from uuid import UUID

from osu_skill_lab.application.lab_contracts import ModelArtifact


class ArtifactUnavailable(RuntimeError):
    pass


class ModelArtifactStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory.resolve()

    def _path(self, model_id: UUID) -> Path:
        path = self.directory / f"{model_id}.json"
        if path.is_symlink() or path.resolve().parent != self.directory:
            raise ArtifactUnavailable("Invalid model artifact path")
        return path

    def save(self, model_id: UUID, artifact: ModelArtifact) -> bytes:
        body = artifact.model_dump_json().encode()
        if len(body) > 65536:
            raise ArtifactUnavailable("Model artifact exceeds byte limit")
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self._path(model_id)
            with path.open("xb") as file:
                file.write(body)
        except OSError:
            raise ArtifactUnavailable("Model artifact storage unavailable") from None
        return hashlib.sha256(body).digest()

    def load(self, model_id: UUID, expected_hash: bytes) -> ModelArtifact:
        try:
            path = self._path(model_id)
            if path.stat().st_size > 65536:
                raise ArtifactUnavailable("Model artifact exceeds byte limit")
            body = path.read_bytes()
            if hashlib.sha256(body).digest() != expected_hash:
                raise ArtifactUnavailable("Model artifact checksum mismatch")
            return ModelArtifact.model_validate_json(body)
        except (OSError, ValueError):
            raise ArtifactUnavailable("Model artifact unavailable") from None

    def remove_owned(self, model_id: UUID, expected_hash: bytes) -> None:
        path = self._path(model_id)
        if path.exists() and hashlib.sha256(path.read_bytes()).digest() == expected_hash:
            path.unlink()
