"""Individual attachment downloader. No browser launch or network entrypoint."""

import json
import os
import re
import tempfile
from pathlib import Path

from checkpoint_descargas import (
    verify_extraction_lifecycle,
    CheckpointError,
    save_checkpoint,
    sha256_file,
    validate_checkpoint_structure,
    validate_windows_filename,
    verify_all_downloads,
)
from navegador_adjuntos import (
    BrowserAccessBlocked,
    BrowserDiscoveryError,
    DOWNLOAD_CONTROL_SELECTOR,
    check_access,
)


class IndividualDownloadError(RuntimeError):
    """An individual attachment could not be safely downloaded."""


def validate_control_id(control_id):
    if not isinstance(control_id, str) or re.fullmatch(
        r"DWNL_grdId_[A-Za-z0-9_]+_search",
        control_id,
    ) is None:
        raise IndividualDownloadError("Invalid attachment control ID.")
    return control_id


def download_one(
    popup,
    tender_id,
    control_id,
    checkpoint,
    checkpoint_path,
    downloads_root,
    extracted_root=None,
    *,
    authorized_ids=None,
):
    """Capture one browser download, verify it, and checkpoint it.

    A file saved immediately before a crash remains untouched.
    The next preflight detects it as untracked and stops for review.
    """
    validate_checkpoint_structure(checkpoint)

    if tender_id not in checkpoint["ids"]:
        raise IndividualDownloadError("Tender not authorized by checkpoint.")

    validate_control_id(control_id)

    root = Path(downloads_root)
    folder = root / tender_id
    destination_checkpoint = Path(checkpoint_path)

    if root.is_symlink() or not root.is_dir():
        raise IndividualDownloadError("Unsafe downloads root.")

    if folder.is_symlink() or (folder.exists() and not folder.is_dir()):
        raise IndividualDownloadError("Unsafe tender folder.")

    if not destination_checkpoint.is_file() or destination_checkpoint.is_symlink():
        raise IndividualDownloadError("Checkpoint must already exist.")

    # Reject changes made to the persisted checkpoint since loading.
    try:
        persisted = json.loads(
            destination_checkpoint.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        raise IndividualDownloadError(
            "Persisted checkpoint cannot be read."
        ) from exc

    if persisted != checkpoint:
        raise IndividualDownloadError(
            "Checkpoint changed on disk; download refused."
        )

    if extracted_root is None:
        verify_all_downloads(checkpoint, root)
    else:
        verify_extraction_lifecycle(
            checkpoint, root, Path(extracted_root),
            authorized_ids=authorized_ids,
        )

    entry = checkpoint["licitaciones"][tender_id]

    existing = [
        record for record in entry["attachments"]
        if record.get("control_id") == control_id
        and record.get("status") in {
            "DOWNLOADED", "EXTRACTED", "CLEANUP_PENDING", "COMPLETE"
        }
    ]

    if existing:
        raise IndividualDownloadError("Control already downloaded.")

    check_access(popup)

    folder.mkdir(exist_ok=True)

    selector = '[id="' + control_id + '"]'

    try:
        with popup.expect_download(timeout=90000) as event:
            popup.locator(selector).click(timeout=20000)
        download = event.value

        failure = download.failure()
        if failure:
            raise IndividualDownloadError(
                "Browser download failed: " + str(failure)
            )

        filename = validate_windows_filename(
            download.suggested_filename
        )

        if len(filename) > 180:
            raise IndividualDownloadError("Filename exceeds safety limit.")

        existing_names = {
            existing_path.name.casefold()
            for existing_path in folder.iterdir()
        }

        if filename.casefold() in existing_names:
            original = Path(filename)
            suffix = original.suffix
            stem = original.name[:-len(suffix)] if suffix else original.name

            # Deterministic name based on the unique attachment control.
            # Preserve the extension and the original filename where possible.
            marker = "__" + control_id
            available = 180 - len(marker) - len(suffix)

            if available < 1:
                raise IndividualDownloadError(
                    "Cannot safely disambiguate duplicate filename."
                )

            filename = (
                stem[:available] + marker + suffix
            )

            validate_windows_filename(filename)

            if filename.casefold() in existing_names:
                raise IndividualDownloadError(
                    "Disambiguated filename also exists; overwrite refused."
                )

        destination = folder / filename

        if destination.exists() or destination.is_symlink():
            raise IndividualDownloadError(
                "Existing destination; overwrite refused."
            )

        # Download into a unique temporary file in the same directory.
        # Keep failed or interrupted downloads for recovery inspection.
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".mp-download-",
            suffix=".part",
            dir=folder,
        )
        os.close(descriptor)
        temporary_path = Path(temporary_name)

        download.save_as(str(temporary_path))

        size, digest = sha256_file(temporary_path)

        if size <= 0:
            raise IndividualDownloadError("Downloaded file is empty.")

        # Publish atomically without overwriting an existing destination.
        # Both paths are in the same directory/filesystem.
        os.link(temporary_path, destination)

        published_size, published_digest = sha256_file(destination)

        if (published_size, published_digest) != (size, digest):
            raise IndividualDownloadError(
                "Published attachment integrity mismatch."
            )

        # A crash before this point leaves evidence for recovery inspection.
        temporary_path.unlink()

        record = {
            "control_id": control_id,
            "status": "DOWNLOADED",
            "filename": filename,
            "size_bytes": size,
            "sha256": digest,
        }

        entry["attachments"].append(record)

        try:
            validate_checkpoint_structure(checkpoint)
            save_checkpoint(destination_checkpoint, checkpoint)
        except Exception:
            # The file remains on disk for recovery inspection.
            # Restore the in-memory manifest to its last committed state.
            entry["attachments"].pop()
            raise

        return record

    except BrowserAccessBlocked:
        raise
    except Exception as exc:
        # A restriction discovered after a failed click is not a normal
        # attachment error and must stop the batch.
        check_access(popup)
        if isinstance(exc, IndividualDownloadError):
            raise
        if isinstance(exc, CheckpointError):
            raise IndividualDownloadError(str(exc)) from exc
        raise IndividualDownloadError(
            f"{type(exc).__name__}: {exc}"
        ) from exc
