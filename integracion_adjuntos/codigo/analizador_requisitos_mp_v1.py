#!/usr/bin/env python3
"""Read-only, evidence-first Mercado Publico cached document analyzer (v1).

Reads Hybrid Reader JSON cache; writes reports ONLY to an independent output directory.
Never changes the cache, original documents, or production filter.
"""
from __future__ import annotations
import argparse
import csv
import json
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_CACHE = Path.home() / 'Documents' / 'Filtro_Grandes_Licitaciones' / 'pruebas_adjuntos' / 'lectura_hibrida_2026-11-10' / 'cache'
DEFAULT_OUTPUT = Path.home() / 'Documents' / 'Filtro_Grandes_Licitaciones' / 'pruebas_adjuntos' / 'analisis_requisitos_v1_2026-11-10'

RULES = {
    'presupuesto': [r'presupuesto\s+(?:maximo|disponible|referencial|estimado)', r'presupuesto\s+total', r'monto\s+maximo', r'financiamiento', r'presupuesto'],
    'adjudicacion_lineas': [r'adjudic\w*\s+(?:a\s+un\s+solo\s+oferente\s+)?por\s+linea', r'evaluaci\w*\s+(?:de\s+forma\s+)?individual\s+por\s+linea', r'ofert\w*\s+por\s+(?:linea|item|partida)', r'por\s+linea', r'por\s+item', r'por\s+partida'],
    'plazo_entrega': [r'plazo\s+(?:maximo\s+)?de\s+entrega', r'entrega\s+(?:en|dentro\s+de|hasta)\s+\d+\s+dias', r'\d+\s+dias\s+(?:habiles|corridos)'],
    'mantenimiento': [r'mantenimiento\s+(?:preventivo|correctivo)', r'mantencion\s+(?:preventiva|correctiva)', r'servicio\s+de\s+mantenimiento', r'mantenimiento'],
    'instalacion': [r'instalacion', r'puesta\s+en\s+marcha', r'conexion'],
    'capacitacion': [r'capacitacion', r'entrenamiento'],
    'garantia': [r'garantia\w*', r'canje\s+por\s+calidad'],
    'cantidades': [r'cantidad\w*', r'\bunidad(?:es)?\b', r'\bitem\b'],
    'objeto_contratacion': [r'licitacion\s+publica\s+denominada', r'adquisicion\s+de', r'compra\s+por\s+suministro', r'contratacion\s+de', r'servicios?\s+de\s+(?:mantenimiento|mantencion)'],
}

# Explicit monetary currency required; do not treat UTM, bare dates or percentages as CLP.
MONEY = re.compile(r'(?<!\w)(?:\$\s*|\bCLP\s*)(\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?|\d{5,12})(?!\d)', re.I)
BUDGET_WORDS = re.compile(r'presupuesto|financiamiento|monto\s+(?:maximo|disponible|total|estimado)|valor\s+referencial', re.I)
BUDGET_PRIORITY = [
    ('maximo', re.compile(r'presupuesto\s+(?:maximo\s+disponible|maximo)|monto\s+maximo', re.I)),
    ('referencial', re.compile(r'presupuesto\s+(?:total\s+)?referencial|presupuesto\s+referencial|valor\s+referencial', re.I)),
    ('estimado', re.compile(r'presupuesto\s+estimado|monto\s+estimado', re.I)),
]


def normalized(s: str) -> str:
    # Length-preserving normalization helps map regex offsets to source text.
    chars = []
    for ch in s.casefold():
        decomp = unicodedata.normalize('NFKD', ch)
        chars.append(''.join(x for x in decomp if not unicodedata.combining(x)) or ' ')
    return ''.join(chars)


def snippet(text: str, start: int, end: int, radius: int = 220) -> str:
    return ' '.join(text[max(0, start-radius):min(len(text), end+radius)].split())[:700]


def parse_clp(s: str) -> int | None:
    digits = re.sub(r'\D', '', s)
    # If it looks like Chilean thousands grouping, all digits represent integer pesos.
    if not digits:
        return None
    return int(digits)


def find_evidence(cache_root: Path):
    grouped = defaultdict(list)
    documents = defaultdict(int)
    errors = []
    for folder in sorted(cache_root.iterdir()):
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob('*.json')):
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
                if not isinstance(data, dict) or not isinstance(data.get('segments'), list):
                    raise ValueError('Invalid cache schema')
                docname = data.get('source_name') or path.name
                documents[folder.name] += 1
                for segment in data['segments']:
                    if not isinstance(segment, dict):
                        continue
                    raw = segment.get('text', '')
                    if not isinstance(raw, str) or not raw.strip():
                        continue
                    norm = normalized(raw)
                    base = {'licitacion': folder.name, 'archivo': docname,
                            'localizador': str(segment.get('locator', '')), 'metodo': str(segment.get('method', ''))}
                    for category, patterns in RULES.items():
                        # Up to two matches per segment per category, to limit boilerplate.
                        seen = set()
                        for pattern in patterns:
                            for match in re.finditer(pattern, norm, re.I):
                                if any(abs(match.start()-p) < 65 for p in seen):
                                    continue
                                seen.add(match.start())
                                grouped[folder.name].append({**base, 'categoria': category,
                                    'valor': '', 'tipo': '', 'evidencia': snippet(raw, match.start(), match.end()),
                                    'observacion': 'Coincidencia contextual; requiere revisión'})
                                if len(seen) >= 2:
                                    break
                            if len(seen) >= 2:
                                break
                    # Candidate amounts: retain nearby context; DO NOT equate all amounts to total budgets.
                    for m in MONEY.finditer(raw):
                        lo, hi = max(0, m.start()-350), min(len(raw), m.end()+350)
                        context = normalized(raw[lo:hi])
                        if not BUDGET_WORDS.search(context):
                            continue
                        amount = parse_clp(m.group(1))
                        if amount is None:
                            continue
                        nearby = normalized(raw[max(0,m.start()-180):min(len(raw),m.end()+180)])
                        kind = 'indeterminado'
                        for label, regex in BUDGET_PRIORITY:
                            if regex.search(nearby):
                                kind = label
                                break
                        note = 'Candidato monetario, NO confirmado como presupuesto total'
                        if 'por linea' in nearby or 'precio unitario' in nearby or 'valor unitario' in nearby:
                            note += '; posible monto por línea o unitario'
                        grouped[folder.name].append({**base, 'categoria': 'monto_candidato',
                            'valor': str(amount), 'tipo': kind,
                            'evidencia': snippet(raw, m.start(), m.end(), 300), 'observacion': note})
            except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
                errors.append(f'{path}: {type(exc).__name__}: {exc}')
    return grouped, documents, errors


def summarize(ident, rows, doc_count):
    categories = {r['categoria'] for r in rows}
    candidates = [r for r in rows if r['categoria'] == 'monto_candidato']
    # Intentionally do not automatically select the largest or first amount.
    unique_amounts = sorted({int(r['valor']) for r in candidates})
    return {
        'licitacion': ident,
        'documentos_cache': doc_count,
        'evidencias': len(rows),
        'montos_candidatos_clp': '; '.join(map(str, unique_amounts)),
        'presupuesto_total_clp': '',
        'tipo_presupuesto': 'Por verificar',
        'tipo_contratacion': 'Por verificar',
        'adjudicacion_por_linea': 'Por verificar',
        'plazo_entrega': 'Por verificar',
        'instalacion_requerida': 'Por verificar',
        'mantenimiento_requerido': 'Por verificar',
        'capacitacion_requerida': 'Por verificar',
        'garantia_requerida': 'Por verificar',
        'categorias_con_evidencia': '; '.join(sorted(categories)),
        'estado': 'REVISIÓN MANUAL PENDIENTE',
    }


def write_csv(path, rows, fields):
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cache', type=Path, default=DEFAULT_CACHE)
    p.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    args = p.parse_args(argv)
    cache = args.cache.expanduser().resolve(strict=True)
    if not cache.is_dir():
        p.error('Cache path is not a directory')
    output = args.output.expanduser().resolve()
    # Prevent output being inside cache or overwriting source files.
    if output == cache or cache in output.parents or output in cache.parents:
        p.error('Output must be separate from cache (not an ancestor or descendant)')
    if output.exists() and output.is_symlink():
        p.error('Output cannot be a symbolic link')
    grouped, documents, errors = find_evidence(cache)
    if not documents:
        p.error('No cache documents found')
    output.mkdir(parents=True, exist_ok=True)
    evidence = [r for ident in sorted(documents) for r in grouped[ident]]
    summaries = [summarize(ident, grouped[ident], documents[ident]) for ident in sorted(documents)]
    evidence_fields = ['licitacion', 'archivo', 'localizador', 'metodo', 'categoria', 'valor', 'tipo', 'evidencia', 'observacion']
    summary_fields = list(summaries[0])
    write_csv(output / 'evidencias.csv', evidence, evidence_fields)
    write_csv(output / 'resumen_licitaciones.csv', summaries, summary_fields)
    result = {'version': '1.0', 'generated_utc': datetime.now(timezone.utc).isoformat(),
              'cache_source': str(cache), 'mode': 'EVIDENCE_ONLY_NO_AUTO_DECISIONS',
              'licitaciones': summaries, 'evidencias': evidence, 'errores': errors}
    (output / 'analisis.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('ANALIZADOR DE REQUISITOS v1 — SOLO EVIDENCIA')
    print('Cache (solo lectura):', cache)
    print('Reportes:', output)
    for summary in summaries:
        print(f"{summary['licitacion']} | documentos={summary['documentos_cache']} | evidencias={summary['evidencias']} | montos_candidatos={len(summary['montos_candidatos_clp'].split('; ')) if summary['montos_candidatos_clp'] else 0}")
    print('TOTAL:', len(summaries), 'licitaciones,', sum(documents.values()), 'documentos,', len(evidence), 'evidencias')
    print('Errores:', len(errors))
    print('Sin decisiones automáticas de inclusión/exclusión.')
    return 0 if not errors else 2


if __name__ == '__main__':
    raise SystemExit(main())
