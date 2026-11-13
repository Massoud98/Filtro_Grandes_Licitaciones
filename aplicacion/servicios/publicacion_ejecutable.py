"""Verified, non-clobbering executable publication."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import uuid
from pathlib import Path

from aplicacion.servicios.bloqueo_publicacion import publication_lock


class PublicationError(RuntimeError):
    """Executable publication cannot proceed safely."""


class PublicationVerificationError(PublicationError):
    """Publication completed, but final verification failed."""

    def __init__(
        self,
        *,
        expected_sha256: str,
        previous_sha256: str | None,
        published_path: str | Path,
        backup_path: str | Path | None,
    ):
        super().__init__(
            "Executable publication completed, but final "
            "SHA256 verification failed. Manual recovery "
            "review is required."
        )

        self.expected_sha256 = expected_sha256
        self.previous_sha256 = previous_sha256
        self.published_path = str(published_path)
        self.backup_path = (
            str(backup_path) if backup_path is not None else None
        )
        self.replacement_completed = True


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def _is_redirected_path(path: Path) -> bool:
    """Detect symbolic links and Windows directory junctions."""

    if path.is_symlink():
        return True

    return (
        hasattr(path, "is_junction")
        and path.is_junction()
    )


def _has_redirected_ancestor(path: Path) -> bool:
    """Reject redirection anywhere in a path's parent chain."""

    current = path

    while True:
        if _is_redirected_path(current):
            return True

        if current == current.parent:
            return False

        current = current.parent


def _regular_file(path: Path) -> bool:
    return path.is_file() and not _is_redirected_path(path)


def publish_executable(
    built_exe: str | Path,
    published_exe: str | Path,
    backup_directory: str | Path,
) -> dict:
    published = Path(published_exe)

    with publication_lock(published):
        return _publish_executable_locked(
            built_exe,
            published,
            backup_directory,
        )


def _publish_executable_locked(
    built_exe: str | Path,
    published_exe: str | Path,
    backup_directory: str | Path,
) -> dict:
    built = Path(built_exe)
    published = Path(published_exe)
    backups = Path(backup_directory)

    if not _regular_file(built):
        raise PublicationError("Built executable missing or unsafe.")

    if published.exists() and not _regular_file(published):
        raise PublicationError("Published executable is unsafe.")

    if (
        not backups.is_dir()
        or _has_redirected_ancestor(backups)
    ):
        raise PublicationError("Backup directory missing or unsafe.")

    if (
        not published.parent.is_dir()
        or _has_redirected_ancestor(published.parent)
    ):
        raise PublicationError("Publication directory is unsafe.")

    if _has_redirected_ancestor(built.parent):
        raise PublicationError("Build directory is unsafe.")

    if built.resolve() == published.resolve():
        raise PublicationError("Source and destination are identical.")

    new_hash = sha256_file(built)
    old_hash = sha256_file(published) if published.exists() else None

    backup_path = None

    if old_hash is not None:
        backup_name = (
            f"{published.stem}_{uuid.uuid4().hex}.bak"
        )
        backup_path = backups / backup_name

        descriptor = os.open(
            backup_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )

        try:
            with os.fdopen(descriptor, "wb") as output:
                with published.open("rb") as source:
                    shutil.copyfileobj(source, output)

                output.flush()
                os.fsync(output.fileno())
        except BaseException:
            raise

        if sha256_file(backup_path) != old_hash:
            raise PublicationError("Backup verification failed.")

    temporary = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=".pending_executable_",
            suffix=".tmp",
            dir=published.parent,
            delete=False,
        ) as output:
            temporary = Path(output.name)

            with built.open("rb") as source:
                shutil.copyfileobj(source, output)

            output.flush()
            os.fsync(output.fileno())

        if sha256_file(temporary) != new_hash:
            raise PublicationError("Staged executable verification failed.")

        if old_hash is not None:
            if not _regular_file(published):
                raise PublicationError("Published executable changed.")

            if sha256_file(published) != old_hash:
                raise PublicationError("Published executable changed.")

        if old_hash is None:
            try:
                os.link(temporary, published)
            except FileExistsError:
                raise PublicationError(
                    "Destination appeared during first publication."
                ) from None

        else:
            os.replace(temporary, published)
            temporary = None

    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()

    if sha256_file(published) != new_hash:
        raise PublicationVerificationError(
            expected_sha256=new_hash,
            previous_sha256=old_hash,
            published_path=published,
            backup_path=backup_path,
        )

    return {
        "new_sha256": new_hash,
        "previous_sha256": old_hash,
        "backup": str(backup_path) if backup_path else None,
    }
