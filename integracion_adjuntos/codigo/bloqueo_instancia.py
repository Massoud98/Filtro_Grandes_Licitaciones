"""Windows single-instance guard for the attachment pilot."""

import msvcrt
from contextlib import contextmanager
from pathlib import Path


class InstanceAlreadyRunning(RuntimeError):
    pass


@contextmanager
def single_instance(path):
    lock_path = Path(path)

    if lock_path.is_symlink():
        raise RuntimeError("Unsafe lock file.")

    if not lock_path.parent.is_dir():
        raise RuntimeError("Lock directory missing.")

    with lock_path.open("a+b") as stream:
        stream.seek(0, 2)

        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()

        stream.seek(0)

        try:
            msvcrt.locking(
                stream.fileno(),
                msvcrt.LK_NBLCK,
                1,
            )
        except OSError as exc:
            raise InstanceAlreadyRunning(
                "Another attachment pilot is already running."
            ) from exc

        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(
                stream.fileno(),
                msvcrt.LK_UNLCK,
                1,
            )
