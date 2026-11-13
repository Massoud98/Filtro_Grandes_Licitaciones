"""Windows cross-process lock for executable publication."""

from __future__ import annotations

import msvcrt
import os
import time
from contextlib import contextmanager
from pathlib import Path


class PublicationLockError(RuntimeError):
    """Publication lock could not be acquired safely."""


@contextmanager
def publication_lock(
    published_exe: str | Path,
    timeout: float = 90,
):
    """Serialize cooperating executable publication processes."""

    published = Path(published_exe)

    if not published.parent.is_dir() or published.parent.is_symlink():
        raise PublicationLockError("Unsafe publication directory.")

    lock_path = published.with_name(
        published.name + ".publication.lock"
    )

    if lock_path.is_symlink():
        raise PublicationLockError("Unsafe publication lock path.")

    start = time.monotonic()

    with open(lock_path, "a+b") as stream:
        acquired = False

        while not acquired:
            try:
                stream.seek(0)
                msvcrt.locking(
                    stream.fileno(),
                    msvcrt.LK_NBLCK,
                    1,
                )
                acquired = True

            except OSError as exc:
                if (
                    getattr(exc, "winerror", None) not in (33, 36)
                    and not isinstance(exc, PermissionError)
                ):
                    raise

                if time.monotonic() - start >= timeout:
                    raise PublicationLockError(
                        "Timed out waiting for publication lock."
                    ) from None

                time.sleep(0.2)

        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(
                stream.fileno(),
                msvcrt.LK_UNLCK,
                1,
            )
