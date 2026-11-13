"""Read-only extraction audit for the 2026-11-10 attachment pilot.

Does not modify source attachments. Outputs a CSV report in the pilot folder.
"""
from __future__ import annotations

import csv
from collections import Counter
from datetime import datetime
from pathlib import Path

import pymupdf
from docx import Document

ROOT = Path.home() / 'Documents' / 'Filtro_Grandes_Licitaciones' / 'pruebas_adjuntos' / '2026-11-10'
FIELDS = ('licitacion', 'archivo', 'formato', 'tamano_kb', 'paginas', 'paginas_sin_texto', 'parrafos', 'tablas', 'caracteres_extraidos', 'estado', 'detalle')


def inspect_pdf(path: Path) -> dict:
    with pymupdf.open(path) as doc:
        if doc.needs_pass:
            return dict(paginas=len(doc), paginas_sin_texto='', caracteres_extraidos=0,
                        estado='REQUIERE_CLAVE', detalle='PDF protegido con contraseña')
        total = 0
        blank = 0
        for page in doc:
            text = page.get_text('text')
            n = len(text.strip())
            total += n
            if n < 30:
                blank += 1
        return dict(paginas=len(doc), paginas_sin_texto=blank,
                    caracteres_extraidos=total,
                    estado='REVISAR_PDF' if blank else 'OK',
                    detalle='Una o más páginas tienen menos de 30 caracteres' if blank else '')


def inspect_docx(path: Path) -> dict:
    doc = Document(path)
    paragraphs = [p.text for p in doc.paragraphs]
    table_text = []
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                table_text.append(cell.text)
    # This is an extraction audit, not a complete OOXML coverage guarantee.
    count = sum(len(s.strip()) for s in paragraphs + table_text)
    return dict(parrafos=len(doc.paragraphs), tablas=len(doc.tables),
                caracteres_extraidos=count,
                estado='REVISAR_DOCX' if count < 30 else 'OK',
                detalle='Poco texto visible en párrafos y tablas' if count < 30 else '')


def main() -> None:
    if not ROOT.is_dir():
        raise SystemExit(f'No existe la carpeta: {ROOT}')
    files = sorted(p for p in ROOT.iterdir() if p.is_dir() and not p.is_symlink()
                   for p in p.iterdir() if p.is_file() and not p.is_symlink()
                   and p.suffix.lower() in {'.pdf', '.docx'})
    print('CARPETA:', ROOT)
    print('DOCUMENTOS ENCONTRADOS:', len(files))
    if not files:
        raise SystemExit('No se encontraron PDF o DOCX.')
    records = []
    for path in files:
        result = {key: '' for key in FIELDS}
        result.update(licitacion=path.parent.name, archivo=path.name,
                      formato=path.suffix.lower(), tamano_kb=round(path.stat().st_size / 1024, 1))
        try:
            result.update(inspect_pdf(path) if path.suffix.lower() == '.pdf' else inspect_docx(path))
        except Exception as exc:
            result.update(estado='ERROR', detalle=f'{type(exc).__name__}: {str(exc)[:200]}')
        records.append(result)
        print(f"{result['licitacion']} | {result['formato']} | {result['estado']} | "
              f"{result['caracteres_extraidos']} caracteres | {result['archivo']}")
    out = ROOT / f'auditoria_lectura_{datetime.now():%Y%m%d_%H%M%S}.csv'
    with out.open('w', newline='', encoding='utf-8-sig') as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(records)
    print('\nRESUMEN:', dict(Counter(r['estado'] for r in records)))
    print('REPORTE:', out)
    print('Los documentos originales no fueron modificados.')


if __name__ == '__main__':
    main()
