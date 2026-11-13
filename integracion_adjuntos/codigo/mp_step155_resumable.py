"""Step 155: resumable Mercado Publico attachment downloader.

Preserves Step 153 downloads, uses separate output/checkpoint,
never overwrites attachments, and stops on access restrictions.
"""
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

ROOT = Path.home() / "Documents" / "Filtro_Grandes_Licitaciones"
OLD = ROOT / "descarga_temporal_step153_five_licitaciones"
OUT = ROOT / "descarga_temporal_step155_resumable"
PROFILE = ROOT / "chrome_playwright_step155_profile"
CHECKPOINT = OUT / "checkpoint.json"
SELECTOR = 'input[type="image"][id^="DWNL_grdId_"][id$="_search"]'
ATTACHMENT_DELAY = 2
LICITACION_DELAY = 5


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(chunk)
            h.update(chunk)
    return size, h.hexdigest()


def safe_name(value):
    name = Path(value.replace("\\", "/")).name
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    if not name or name in (".", ".."):
        raise ValueError("Unsafe filename")
    return name[:180]


def save_checkpoint(data):
    temp = CHECKPOINT.with_suffix(".json.tmp")
    if temp.exists() or temp.is_symlink():
        raise RuntimeError("STOP: unexpected checkpoint temp file")
    with temp.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, CHECKPOINT)


def verified(record, folder):
    if record.get("status") != "DOWNLOADED":
        return False
    filename = record.get("filename")
    if not isinstance(filename, str) or safe_name(filename) != filename:
        return False
    path = folder / filename
    if path.is_symlink() or not path.is_file():
        return False
    size, sha = digest(path)
    return size == record.get("size_bytes") and sha == record.get("sha256")


def blocked(page):
    url = page.url.lower()
    if "/403.html" in url:
        return True
    try:
        body = page.locator("body").inner_text(timeout=3000).lower()
        return ("abnormal activity" in body or
                "actividad anormal" in body)
    except Exception:
        return False


def run():
    if not ROOT.is_dir():
        raise RuntimeError("STOP: project directory missing")

    old_manifest = OLD / "manifest.json"
    original = json.loads(old_manifest.read_text(encoding="utf-8"))
    ids = original["ids"]

    if OUT.is_symlink() or PROFILE.is_symlink():
        raise RuntimeError("STOP: unsafe output/profile symlink")
    OUT.mkdir(exist_ok=True)

    if CHECKPOINT.exists():
        data = json.loads(CHECKPOINT.read_text(encoding="utf-8"))
        if data.get("ids") != ids:
            raise RuntimeError("STOP: checkpoint IDs differ")
    else:
        data = {
            "created_utc": now(),
            "ids": ids,
            "licitaciones": {}
        }
        for lic in ids:
            old_entry = original["licitaciones"][lic]
            records = []
            for record in old_entry["attachments"]:
                if record.get("status") == "DOWNLOADED":
                    if not verified(record, OLD / lic):
                        raise RuntimeError(
                            "STOP: Step 153 file failed verification: " + lic
                        )
                    copied = dict(record)
                    copied["source"] = "STEP153"
                    records.append(copied)
            data["licitaciones"][lic] = {
                "status": "PENDING",
                "discovered": old_entry.get("discovered"),
                "attachments": records,
                "errors": []
            }
        save_checkpoint(data)

    # Recheck all previously recorded downloads before browsing.
    for lic in ids:
        entry = data["licitaciones"][lic]
        for record in entry["attachments"]:
            if record.get("status") != "DOWNLOADED":
                continue
            folder = OLD / lic if record.get("source") == "STEP153" else OUT / lic
            if not verified(record, folder):
                raise RuntimeError(
                    "STOP: checkpoint file missing or changed: " + lic
                )

    pending = [
        lic for lic in ids
        if data["licitaciones"][lic]["status"] != "COMPLETE"
    ]

    # Step 153 completed licitaciones can be skipped without reopening.
    for lic in pending[:]:
        original_entry = original["licitaciones"][lic]
        if original_entry["status"] == "COMPLETE":
            entry = data["licitaciones"][lic]
            count = sum(
                r["status"] == "DOWNLOADED"
                for r in entry["attachments"]
            )
            if count == original_entry.get("discovered"):
                entry["status"] = "COMPLETE"
                pending.remove(lic)
    save_checkpoint(data)

    print("=== STEP 155 — RESUMABLE DOWNLOADER ===", flush=True)
    print("Pending licitaciones:", pending, flush=True)
    print("Attachment delay:", ATTACHMENT_DELAY, "seconds", flush=True)
    print("Licitacion delay:", LICITACION_DELAY, "seconds", flush=True)

    if not pending:
        print("ALL COMPLETE. No browser launched.", flush=True)
        return

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE),
            channel="chrome",
            headless=False,
            accept_downloads=True,
            viewport={"width": 1366, "height": 900},
        )
        try:
            for position, lic in enumerate(pending):
                if position:
                    time.sleep(LICITACION_DELAY)

                entry = data["licitaciones"][lic]
                folder = OUT / lic
                folder.mkdir(exist_ok=True)
                print("\nLICITACION:", lic, flush=True)

                page = context.new_page()
                popup = None
                try:
                    url = (
                        "https://www.mercadopublico.cl/Procurement/"
                        "Modules/RFB/DetailsAcquisition.aspx?idlicitacion="
                        + quote(lic)
                    )
                    response = page.goto(
                        url, wait_until="domcontentloaded", timeout=45000
                    )
                    status = response.status if response else None
                    print("Ficha HTTP:", status, flush=True)
                    if status == 403 or blocked(page):
                        raise PermissionError("403/abnormal activity on ficha")
                    if status != 200:
                        raise RuntimeError("Unexpected ficha HTTP status")

                    control = page.locator("#imgAdjuntos")
                    if control.count() != 1:
                        raise RuntimeError("Attachment control not found")

                    with page.expect_popup(timeout=20000) as event:
                        control.click(timeout=15000)
                    popup = event.value

                    try:
                        popup.wait_for_url(
                            "**/Attachment/ViewAttachmentLC.aspx*",
                            timeout=35000,
                        )
                    except PWTimeout:
                        if blocked(popup):
                            raise PermissionError(
                                "403/abnormal activity on attachments"
                            )
                        raise

                    popup.wait_for_load_state(
                        "domcontentloaded", timeout=25000
                    )
                    if blocked(popup):
                        raise PermissionError(
                            "403/abnormal activity on attachments"
                        )

                    popup.locator(SELECTOR).first.wait_for(
                        state="visible", timeout=15000
                    )
                    controls = popup.locator(SELECTOR).evaluate_all(
                        "(els) => els.map(e => e.id)"
                    )
                    if len(controls) != len(set(controls)):
                        raise RuntimeError("Duplicate attachment controls")

                    entry["discovered"] = len(controls)
                    save_checkpoint(data)
                    print("Discovered:", len(controls), flush=True)

                    for index, control_id in enumerate(controls, 1):
                        existing = [
                            r for r in entry["attachments"]
                            if r.get("control_id") == control_id
                            and r.get("status") == "DOWNLOADED"
                        ]
                        if existing:
                            print("SKIP verified:", control_id, flush=True)
                            continue

                        print(
                            f"[{index}/{len(controls)}] {control_id}",
                            flush=True,
                        )
                        try:
                            with popup.expect_download(timeout=90000) as event:
                                popup.locator(
                                    '[id="' + control_id + '"]'
                                ).click(timeout=20000)
                            download = event.value
                            failure = download.failure()
                            if failure:
                                raise RuntimeError(str(failure))

                            filename = safe_name(
                                download.suggested_filename
                            )
                            target = folder / filename
                            if target.exists() or target.is_symlink():
                                raise RuntimeError(
                                    "Existing filename; overwrite refused: "
                                    + filename
                                )
                            download.save_as(str(target))
                            size, sha = digest(target)
                            if size == 0:
                                raise RuntimeError("Empty downloaded file")

                            with target.open("rb") as stream:
                                header = stream.read(5)
                            record = {
                                "control_id": control_id,
                                "index": index,
                                "status": "DOWNLOADED",
                                "filename": filename,
                                "size_bytes": size,
                                "sha256": sha,
                                "pdf_header_valid": (
                                    header == b"%PDF-"
                                    if filename.lower().endswith(".pdf")
                                    else None
                                ),
                                "source": "STEP155",
                                "timestamp_utc": now(),
                            }
                            entry["attachments"].append(record)
                            save_checkpoint(data)
                            print("SAVED:", filename, size, flush=True)
                        except Exception as exc:
                            if blocked(popup):
                                raise PermissionError(
                                    "403/abnormal activity during download"
                                ) from exc
                            entry["errors"].append(
                                f"{control_id}: {type(exc).__name__}: {exc}"
                            )
                            save_checkpoint(data)
                            print("DOWNLOAD ERROR:", exc, flush=True)

                        time.sleep(ATTACHMENT_DELAY)

                    completed = {
                        r["control_id"] for r in entry["attachments"]
                        if r.get("status") == "DOWNLOADED"
                    }
                    entry["status"] = (
                        "COMPLETE"
                        if all(c in completed for c in controls)
                        else "PARTIAL"
                    )
                    save_checkpoint(data)
                except PermissionError as exc:
                    entry["status"] = "BLOCKED"
                    entry["errors"].append(str(exc))
                    save_checkpoint(data)
                    print("ACCESS RESTRICTION — STOPPING:", exc, flush=True)
                    print("Resume by running this script again later.")
                    break
                except Exception as exc:
                    entry["status"] = "ERROR"
                    entry["errors"].append(
                        f"{type(exc).__name__}: {exc}"
                    )
                    save_checkpoint(data)
                    print("LICITACION ERROR:", exc, flush=True)
                finally:
                    if popup and not popup.is_closed():
                        popup.close()
                    if not page.is_closed():
                        page.close()
        finally:
            context.close()

    print("\nCheckpoint:", CHECKPOINT)
    for lic in ids:
        entry = data["licitaciones"][lic]
        count = sum(
            r.get("status") == "DOWNLOADED"
            for r in entry["attachments"]
        )
        print(lic, entry["status"], count, "downloaded")
    print("No cleanup performed. No existing files overwritten.")


if __name__ == "__main__":
    run()