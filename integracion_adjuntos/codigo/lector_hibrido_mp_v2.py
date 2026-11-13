"""Lector híbrido MP v1: extracción verificable, caché y auditoría; sin decisiones automáticas.

Por defecto: DOCX y PDF con texto completos; OCR de hasta 2 páginas por PDF escaneado.
--full: OCR de todas las páginas pendientes. --status: solo inspecciona el caché.
No altera archivos originales. Requiere python-docx, pymupdf y Tesseract + spa.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from time import perf_counter

ROOT = Path.home() / 'Documents' / 'Filtro_Grandes_Licitaciones'
SOURCE = ROOT / 'pruebas_adjuntos' / '2026-11-10'
OUTPUT = ROOT / 'pruebas_adjuntos' / 'lectura_hibrida_2026-11-10'
TESSERACT = Path(r'C:\Program Files\Tesseract-OCR\tesseract.exe')
TESSDATA = ROOT / 'entorno_pruebas_adjuntos' / 'tessdata'
OCR_DPI = 200
MIN_TEXT_CHARS = 30


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    with temp.open('w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    temp.replace(path)


def load_cache(path: Path, sha: str, source_name: str):
    if not path.is_file():
        return None
    try:
        with path.open(encoding='utf-8') as f:
            obj = json.load(f)
        if (obj.get('schema') == 1 and obj.get('sha256') == sha
                and obj.get('source_name') == source_name
                and isinstance(obj.get('segments'), list)):
            return obj
    except (OSError, ValueError, TypeError):
        pass
    return None


def extract_docx(path: Path):
    from docx import Document
    doc = Document(path)
    segments = []
    for idx, item in enumerate(doc.iter_inner_content(), 1):
        if hasattr(item, 'rows'):
            lines = [' | '.join(c.text.replace('\n', ' / ').strip() for c in row.cells)
                     for row in item.rows]
            txt = '\n'.join(x for x in lines if x.strip())
            kind = 'tabla'
        else:
            txt = item.text.strip()
            kind = 'parrafo'
        if txt:
            segments.append({'locator': f'{kind} {idx}', 'method': 'docx', 'text': txt})
    return segments


def ocr_page(page):
    pix = page.get_pixmap(dpi=OCR_DPI, alpha=False)
    proc = subprocess.run(
        [str(TESSERACT), 'stdin', 'stdout', '--tessdata-dir', str(TESSDATA),
         '-l', 'spa', '--psm', '3'],
        input=pix.tobytes('png'), stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, timeout=120, check=False,
    )
    if proc.returncode:
        raise RuntimeError(proc.stderr.decode('utf-8', 'replace')[:600])
    return proc.stdout.decode('utf-8', 'replace').strip()


def extract_pdf(path: Path, prior: list, full: bool, pilot_pages: int):
    import pymupdf
    existing = {s['locator']: s for s in prior if isinstance(s, dict) and 'locator' in s}
    scanned_ocr_done = sum(1 for s in existing.values() if s.get('method') == 'ocr')
    new_ocr = 0
    errors = []
    with pymupdf.open(path) as doc:
        for i, page in enumerate(doc):
            locator = f'pagina {i + 1}'
            old = existing.get(locator)
            if old and old.get('method') in ('pdf_text', 'ocr'):
                continue
            direct = page.get_text('text').strip()
            if len(direct) >= MIN_TEXT_CHARS:
                existing[locator] = {'locator': locator, 'method': 'pdf_text', 'text': direct}
                continue
            if not full and scanned_ocr_done + new_ocr >= pilot_pages:
                # Empty or near-empty page; not yet OCRed.
                continue
            try:
                result = ocr_page(page)
                existing[locator] = {'locator': locator, 'method': 'ocr', 'text': result}
                new_ocr += 1
            except Exception as exc:
                errors.append(f'{locator}: {type(exc).__name__}: {exc}')
                # Avoid retry loops in the same run; subsequent runs may retry.
        return [existing[k] for k in sorted(existing, key=lambda s: int(s.split()[1]))], len(doc), errors


def report_rows(records, dest):
    report = dest / 'auditoria.csv'
    with report.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['licitacion', 'archivo', 'formato', 'estado',
            'paginas_pdf', 'segmentos', 'paginas_ocr', 'caracteres', 'errores', 'segundos'])
        w.writeheader()
        w.writerows(records)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--full', action='store_true', help='OCR todas las páginas pendientes')
    parser.add_argument('--pilot-pages', type=int, default=2, help='Máximo OCR por PDF en piloto (defecto: 2)')
    parser.add_argument('--status', action='store_true', help='Mostrar caché existente, sin procesar')
    args = parser.parse_args()
    if args.pilot_pages < 0:
        parser.error('--pilot-pages debe ser >= 0')
    if not SOURCE.is_dir():
        raise SystemExit(f'No existe carpeta de adjuntos: {SOURCE}')
    files = sorted((p for p in SOURCE.glob('*/*') if p.is_file() and p.suffix.lower() in ('.pdf', '.docx')),
                   key=lambda p: (p.parent.name, p.name))
    if not files:
        raise SystemExit('No se encontraron PDF/DOCX en las carpetas de licitación.')
    if not args.status and not TESSERACT.is_file():
        raise SystemExit(f'Falta Tesseract: {TESSERACT}')
    if not args.status and not (TESSDATA / 'spa.traineddata').is_file():
        raise SystemExit(f'Falta idioma español: {TESSDATA / "spa.traineddata"}')
    OUTPUT.mkdir(parents=True, exist_ok=True)
    records = []
    print(f'ORIGINALES: {SOURCE}\nCACHE/REPORTES: {OUTPUT}\nARCHIVOS: {len(files)}')
    print('MODO:', 'ESTADO' if args.status else 'COMPLETO' if args.full else f'PILOTO ({args.pilot_pages} páginas OCR por PDF)')
    for path in files:
        t0 = perf_counter()
        ident = path.parent.name
        sha = digest(path)
        # Stable name independent of unicode and unsafe path characters.
        cache_path = OUTPUT / 'cache' / ident / (sha + '.json')
        cached = load_cache(cache_path, sha, path.name)
        obj = cached or {'schema': 1, 'sha256': sha, 'source_name': path.name,
                         'source_relative': f'{ident}/{path.name}', 'segments': [],
                         'pages': None, 'errors': []}
        cached_before = json.loads(json.dumps(cached, ensure_ascii=False)) if cached is not None else None
        state = 'CACHE_ONLY' if args.status else 'OK'
        try:
            if not args.status:
                if path.suffix.lower() == '.docx':
                    if not cached:
                        obj['segments'] = extract_docx(path)
                else:
                    seg, pages, errors = extract_pdf(path, obj['segments'], args.full, args.pilot_pages)
                    obj['segments'] = seg
                    obj['pages'] = pages
                    obj['errors'] = errors
                    if len(seg) < pages:
                        state = 'PARCIAL'
                if cached is None or obj != cached_before:
                    atomic_json(cache_path, obj)
            elif not cached:
                state = 'SIN_CACHE'
            segments = obj['segments']
            chars = sum(len(s.get('text', '')) for s in segments)
            ocr = sum(s.get('method') == 'ocr' for s in segments)
            errors = obj.get('errors', [])
            if errors:
                state = 'ERROR_PARCIAL'
            print(f'{ident} | {path.suffix.lower()} | {state} | segmentos={len(segments)} | OCR={ocr} | caracteres={chars} | {path.name}')
            records.append(dict(licitacion=ident, archivo=path.name, formato=path.suffix.lower(),
                estado=state, paginas_pdf=obj.get('pages') or '', segmentos=len(segments),
                paginas_ocr=ocr, caracteres=chars, errores='; '.join(errors),
                segundos=round(perf_counter() - t0, 2)))
        except Exception as exc:
            print(f'ERROR {ident}/{path.name}: {type(exc).__name__}: {exc}')
            records.append(dict(licitacion=ident, archivo=path.name, formato=path.suffix.lower(),
                estado='ERROR', paginas_pdf='', segmentos=0, paginas_ocr=0,
                caracteres=0, errores=f'{type(exc).__name__}: {exc}',
                segundos=round(perf_counter() - t0, 2)))
    report = report_rows(records, OUTPUT)
    counts = {state: sum(r['estado'] == state for r in records) for state in sorted({r['estado'] for r in records})}
    print('\nRESUMEN:', counts)
    print('REPORTE:', report)
    print('ORIGINALES: sin modificaciones. Caché: JSON por documento y página/elemento.')


if __name__ == '__main__':
    main()
