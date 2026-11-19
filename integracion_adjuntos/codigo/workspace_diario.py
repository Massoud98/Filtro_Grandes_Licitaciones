"""Resolve date-isolated attachment workspaces without filesystem changes."""

from dataclasses import dataclass
from datetime import date
from pathlib import Path


class WorkspaceResolutionError(ValueError):
    pass


@dataclass(frozen=True)
class AttachmentWorkspace:
    date: str
    root: Path
    downloads: Path
    extracted: Path
    checkpoints: Path


def resolve_workspace(classification_path, workspace_root):
    source = Path(classification_path)
    base = Path(workspace_root)

    if source.is_symlink() or not source.is_file():
        raise WorkspaceResolutionError("Classification source missing or unsafe.")

    if source.name != "filtros_preliminares.json":
        raise WorkspaceResolutionError("Unexpected classification filename.")

    if source.parent.parent.name != "consolidados":
        raise WorkspaceResolutionError("Classification must belong to consolidados.")

    run_date = source.parent.name

    try:
        parsed = date.fromisoformat(run_date)
    except ValueError as exc:
        raise WorkspaceResolutionError("Invalid classification date.") from exc

    if parsed.isoformat() != run_date:
        raise WorkspaceResolutionError("Noncanonical classification date.")

    if base.is_symlink():
        raise WorkspaceResolutionError("Unsafe workspace root.")

    dated = base / run_date

    if dated.is_symlink():
        raise WorkspaceResolutionError("Unsafe dated workspace.")

    return AttachmentWorkspace(
        date=run_date,
        root=dated,
        downloads=dated / "descargas",
        extracted=dated / "extraidos",
        checkpoints=dated / "checkpoints",
    )
