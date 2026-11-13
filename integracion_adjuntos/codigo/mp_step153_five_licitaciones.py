"""Mercado Publico five-licitacion attachment acquisition pilot.

Run on Windows with Python + Playwright installed and Google Chrome available.
No CAPTCHA solving, no overwrites, no automatic deletion.
"""
import csv
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

IDS = [
    '3251-43-CO26',
    '1001-22-LE26',
    '1028-51-LE26',
    '1057390-69-LE26',
    '1058086-67-LE26',
]
ROOT = Path.home() / 'Documents' / 'Filtro_Grandes_Licitaciones'
OUT = ROOT / 'descarga_temporal_step153_five_licitaciones'
PROFILE = ROOT / 'chrome_playwright_step153_profile'
SELECTOR = 'input[type="image"][id^="DWNL_grdId_"][id$="_search"]'


def now():
    return datetime.now(timezone.utc).isoformat()


def digest_file(path):
    sha = hashlib.sha256()
    size = 0
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            sha.update(chunk)
            size += len(chunk)
    return size, sha.hexdigest()


def safe_filename(name):
    # Windows restrictions, plus path traversal protection.
    name = Path(name.replace('\\', '/')).name
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip(' .')
    if not name or name in {'.', '..'}:
        raise ValueError('Unsafe suggested filename')
    return name[:180]


def atomic_json(path, data):
    # Exclusive new file on first write; subsequent updates replace only our own manifest.
    temp = path.with_suffix('.json.tmp')
    if temp.exists():
        raise RuntimeError(f'STOP: unexpected temp manifest exists: {temp}')
    with temp.open('x', encoding='utf-8') as stream:
        json.dump(data, stream, indent=2, ensure_ascii=False)
        stream.flush()
    temp.replace(path)


def log_record(manifest, lic, record):
    manifest['licitaciones'][lic]['attachments'].append(record)
    atomic_json(OUT / 'manifest.json', manifest)


def run():
    if not ROOT.is_dir():
        raise SystemExit(f'STOP: project folder not found: {ROOT}')
    if OUT.exists() or OUT.is_symlink() or PROFILE.exists() or PROFILE.is_symlink():
        raise SystemExit('STOP: Step 153 output or Chrome profile already exists. Nothing changed.')
    OUT.mkdir(exist_ok=False)
    manifest = {'created_utc': now(), 'ids': IDS, 'licitaciones': {i: {'status': 'PENDING', 'attachments': [], 'errors': []} for i in IDS}}
    atomic_json(OUT / 'manifest.json', manifest)
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE), channel='chrome', headless=False,
            accept_downloads=True, viewport={'width': 1366, 'height': 900},
        )
        try:
            for n, lic in enumerate(IDS, 1):
                entry = manifest['licitaciones'][lic]
                folder = OUT / lic
                folder.mkdir(exist_ok=False)
                entry['status'] = 'RUNNING'
                atomic_json(OUT / 'manifest.json', manifest)
                print(f'\n=== {n}/{len(IDS)} LICITACION {lic} ===', flush=True)
                page = context.new_page()
                popup = None
                try:
                    url = ('https://www.mercadopublico.cl/Procurement/Modules/'
                           'RFB/DetailsAcquisition.aspx?idlicitacion=' + quote(lic))
                    response = page.goto(url, wait_until='domcontentloaded', timeout=45000)
                    print('Ficha HTTP:', response.status if response else 'none', flush=True)
                    if response is None or response.status != 200:
                        raise RuntimeError('Ficha HTTP status not 200')
                    control = page.locator('#imgAdjuntos')
                    if control.count() != 1:
                        raise RuntimeError('Attachment popup control not found')
                    with page.expect_popup(timeout=20000) as info:
                        control.click(timeout=15000)
                    popup = info.value
                    popup.wait_for_url('**/Attachment/ViewAttachmentLC.aspx*', timeout=35000)
                    popup.wait_for_load_state('domcontentloaded', timeout=25000)
                    try:
                        popup.locator(SELECTOR).first.wait_for(state='visible', timeout=15000)
                    except PWTimeout:
                        # Could be genuinely zero attachments or a different layout.
                        if popup.locator(SELECTOR).count() == 0:
                            raise RuntimeError('No individual attachment controls found (verify whether zero attachments)')
                    ids = popup.locator(SELECTOR).evaluate_all('(els) => els.map(e => e.id)')
                    if len(ids) != len(set(ids)):
                        raise RuntimeError('Duplicate attachment control IDs')
                    entry['discovered'] = len(ids)
                    atomic_json(OUT / 'manifest.json', manifest)
                    print('Attachments discovered:', len(ids), flush=True)
                    for j, control_id in enumerate(ids, 1):
                        record = {'control_id': control_id, 'index': j, 'status': 'PENDING', 'timestamp_utc': now()}
                        print(f'  [{j}/{len(ids)}] {control_id}', flush=True)
                        try:
                            with popup.expect_download(timeout=90000) as dl_info:
                                popup.locator('[id="' + control_id + '"]').click(timeout=20000)
                            download = dl_info.value
                            if download.failure():
                                raise RuntimeError('Browser download failed: ' + str(download.failure()))
                            filename = safe_filename(download.suggested_filename)
                            target = folder / filename
                            if target.exists() or target.is_symlink():
                                raise RuntimeError('Duplicate filename, refused overwrite: ' + filename)
                            # save_as may create a file: ensure name is unoccupied immediately beforehand.
                            download.save_as(str(target))
                            size, sha = digest_file(target)
                            with target.open('rb') as fh:
                                signature = fh.read(5)
                            record.update(status='DOWNLOADED', filename=filename,
                                          size_bytes=size, sha256=sha,
                                          pdf_header_valid=(signature == b'%PDF-') if filename.lower().endswith('.pdf') else None)
                            print('     SAVED:', filename, size, 'bytes', flush=True)
                        except Exception as exc:
                            record.update(status='ERROR', error=f'{type(exc).__name__}: {exc}')
                            print('     ERROR:', record['error'][:300], flush=True)
                        log_record(manifest, lic, record)
                        popup.wait_for_timeout(1200)
                    good = sum(r['status'] == 'DOWNLOADED' for r in entry['attachments'])
                    entry['status'] = 'COMPLETE' if good == len(ids) else 'PARTIAL'
                except Exception as exc:
                    entry['status'] = 'ERROR'
                    entry['errors'].append(f'{type(exc).__name__}: {exc}')
                    print('LICITACION ERROR:', entry['errors'][-1][:400], flush=True)
                finally:
                    atomic_json(OUT / 'manifest.json', manifest)
                    if popup and not popup.is_closed():
                        popup.close()
                    if not page.is_closed():
                        page.close()
                    time.sleep(2)
        finally:
            context.close()
    print('\n=== FINAL SUMMARY ===')
    for lic, info in manifest['licitaciones'].items():
        ok = sum(r['status'] == 'DOWNLOADED' for r in info['attachments'])
        print(f'{lic}: {info["status"]} | discovered={info.get("discovered", "?")} | downloaded={ok} | errors={len(info["errors"]) + sum(r["status"] == "ERROR" for r in info["attachments"])}')
    print('Manifest:', OUT / 'manifest.json')
    print('No cleanup performed; no existing files overwritten.')


if __name__ == '__main__':
    run()
