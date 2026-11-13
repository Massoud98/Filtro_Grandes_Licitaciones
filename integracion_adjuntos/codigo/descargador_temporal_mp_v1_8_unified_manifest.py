#!/usr/bin/env python3
"""Isolated, conservative temporary downloader for Mercado Publico attachments.

Input: URL manifest or process_local() API for existing files. Output: independent JSON cache and audit.
Never touches the existing pilot, production folder, or hybrid reader cache.
Requires: pymupdf, python-docx; optional pytesseract/Pillow for OCR (OCR held for review).
"""
from __future__ import annotations
import argparse, csv, hashlib, json, os, re, shutil, stat, tempfile, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path.home() / 'Documents' / 'Filtro_Grandes_Licitaciones' / 'pruebas_adjuntos' / 'descarga_temporal_v1'
MAX_BYTES = 80 * 1024 * 1024
ALLOWED_HOSTS = ('mercadopublico.cl', 'chilecompra.cl')

def utc(): return datetime.now(timezone.utc).isoformat()
def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()
def safe_id(value):
    if not re.fullmatch(r'\d{3,9}-\d{1,8}-(?:LE|LP|LQ|LR|CO|B2|H2|I2|L1|O1)\d{2}',value,re.I):
        raise ValueError('Invalid licitacion ID')
    return value.upper()
def allowed(url):
    p=urllib.parse.urlsplit(url)
    return p.scheme=='https' and p.hostname is not None and any(p.hostname==h or p.hostname.endswith('.'+h) for h in ALLOWED_HOSTS) and not p.username and not p.password
class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        if not allowed(newurl): raise ValueError('Redirect outside trusted hosts')
        return super().redirect_request(req,fp,code,msg,headers,newurl)

def download(url,target,descriptor):
    if not allowed(url):
        raise ValueError('URL outside trusted hosts or not HTTPS')

    opener=urllib.request.build_opener(SafeRedirect)
    req=urllib.request.Request(
        url,
        headers={'User-Agent':'Mozilla/5.0 (compatible; MP attachment reader)'}
    )

    with os.fdopen(descriptor,'wb') as out:
        with opener.open(req,timeout=45) as response:
            size=0
            while True:
                chunk=response.read(1024*1024)
                if not chunk:
                    break
                size+=len(chunk)
                if size>MAX_BYTES:
                    raise ValueError('Download exceeds 80 MB safety limit')
                out.write(chunk)

        out.flush()
        os.fsync(out.fileno())

    if size==0:
        raise ValueError('Empty download')

    return size

def extract(path, *, ocr_enabled=False):
    import pymupdf
    from docx import Document

    if not isinstance(ocr_enabled, bool):
        raise TypeError('ocr_enabled must be a boolean')
    head=path.open('rb').read(8)
    segments=[]; pages=0; hold=[]
    if head.startswith(b'%PDF-'):
        doc=pymupdf.open(path)
        try:
            if doc.needs_pass: raise ValueError('Password-protected PDF')
            pages=len(doc)
            if pages==0: raise ValueError('PDF has no pages')

            for i,page in enumerate(doc):
                text=page.get_text('text').strip()
                locator=f'pagina {i+1}'

                if text:
                    segments.append({
                        'locator':locator,
                        'method':'pdf_text',
                        'text':text
                    })
                    continue

                if ocr_enabled:
                    try:
                        from mp_spanish_ocr import recognize_page
                        recognized=recognize_page(page)

                        if recognized:
                            segments.append({
                                'locator':locator,
                                'method':'pdf_ocr',
                                'text':recognized
                            })
                            hold.append(
                                f'Page {i+1}: OCR text requires manual verification'
                            )
                            continue

                    except Exception as exc:
                        hold.append(
                            f'Page {i+1}: OCR failed ({type(exc).__name__})'
                        )

                segments.append({
                    'locator':locator,
                    'method':'unresolved',
                    'text':''
                })
                hold.append(
                    f'Page {i+1}: no verified extractable text'
                )
        finally:
            doc.close()
    elif head.startswith(b'PK'):
        doc=Document(path)
        for i,p in enumerate(doc.paragraphs,1):
            if p.text.strip(): segments.append({'locator':f'parrafo {i}','method':'docx','text':p.text})
        for i,t in enumerate(doc.tables,1):
            rows=[' | '.join(c.text for c in row.cells) for row in t.rows]
            content='\n'.join(rows).strip()
            if content: segments.append({'locator':f'tabla {i}','method':'docx','text':content})
        if not segments: hold.append('DOCX has no extracted text')
        # Embedded pictures, drawings, headers, footers, and text boxes can carry requirements.
        if doc.part.rels:
            for rel in doc.part.rels.values():
                if 'image' in rel.reltype: hold.append('DOCX contains image(s); manual verification required'); break
    else:
        raise ValueError('Unsupported attachment signature (expected PDF or DOCX)')
    if not any(s['text'].strip() for s in segments): hold.append('No readable text extracted')
    return segments,pages,hold

def atomic_json(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)

    if path.exists() or path.is_symlink():
        raise FileExistsError(
            'Cache destination already exists; refusing overwrite'
        )

    fd,tmp=tempfile.mkstemp(
        prefix='.pending_',
        suffix='.json',
        dir=path.parent
    )

    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            json.dump(obj,f,ensure_ascii=False,indent=2)
            f.flush()
            os.fsync(f.fileno())

        # Atomic no-overwrite publication on the same filesystem.
        # The link operation fails if the destination already exists.
        os.link(tmp,path)

    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

def verified_cache(record, expected_sha256):
    """Validate complete native extraction; OCR never qualifies."""
    if not isinstance(record, dict):
        return False
    if record.get('sha256') != expected_sha256:
        return False
    if record.get('extraction_status') != 'COMPLETE_TEXT_EXTRACTION':
        return False
    if record.get('errors') != []:
        return False

    segments = record.get('segments')
    if not isinstance(segments, list) or not segments:
        return False

    if not all(
        isinstance(s, dict)
        and isinstance(s.get('text'), str)
        and isinstance(s.get('locator'), str)
        and isinstance(s.get('method'), str)
        and s['method'] in ('pdf_text', 'docx')
        for s in segments
    ):
        return False

    if not any(s['text'].strip() for s in segments):
        return False

    pages = record.get('pages')
    if type(pages) is not int or pages < 0:
        return False

    if pages > 0:
        expected = {f'pagina {i}' for i in range(1, pages + 1)}
        actual = [s['locator'] for s in segments]
        if len(actual) != pages or set(actual) != expected:
            return False
        if not all(s['method'] == 'pdf_text' and s['text'].strip()
                   for s in segments):
            return False

    return True



def verified_review_cache(record, expected_sha256):
    """Validate retained PDF review caches with per-page review reasons."""
    if not isinstance(record, dict):
        return False
    if record.get('sha256') != expected_sha256:
        return False
    if record.get('extraction_status') != 'REVIEW_REQUIRED':
        return False
    if not str(record.get('source_name', '')).lower().endswith('.pdf'):
        return False

    errors = record.get('errors')
    if (
        not isinstance(errors, list)
        or not errors
        or not all(isinstance(e, str) and e.strip() for e in errors)
    ):
        return False

    pages = record.get('pages')
    if type(pages) is not int or pages <= 0:
        return False

    segments = record.get('segments')
    if not isinstance(segments, list) or len(segments) != pages:
        return False

    expected = {f'pagina {i}' for i in range(1, pages + 1)}
    actual = []
    review_pages = {}

    for segment in segments:
        if not isinstance(segment, dict):
            return False

        locator = segment.get('locator')
        method = segment.get('method')
        content = segment.get('text')

        if not isinstance(locator, str) or not isinstance(content, str):
            return False

        if method not in ('pdf_text', 'pdf_ocr', 'unresolved'):
            return False

        if method == 'unresolved' and content.strip():
            return False

        if method == 'pdf_ocr' and not content.strip():
            return False

        actual.append(locator)

        if method in ('pdf_ocr', 'unresolved'):
            review_pages[locator] = method

    if set(actual) != expected or len(set(actual)) != pages:
        return False

    if not review_pages:
        return False

    for locator, method in review_pages.items():
        page_number = locator.split(' ')[1]
        prefix = f'Page {page_number}:'

        matching = [
            error for error in errors
            if error.startswith(prefix)
        ]

        if not matching:
            return False

        if method == 'pdf_ocr':
            if not any('OCR' in error for error in matching):
                return False

        if method == 'unresolved':
            if not any(
                'no extractable text' in error.lower()
                or 'no verified extractable text' in error.lower()
                or 'ocr/visual verification required' in error.lower()
                for error in matching
            ):
                return False

    return True





# Automatic attachment cleanup is disabled in v1.7.



def verify_work_directories(root):
    import stat

    root = Path(root)

    if not root.is_dir() or root.is_symlink():
        raise ValueError('Unsafe downloader root')

    work = root / 'work'
    cache = root / 'cache'

    for directory in (work, cache):
        if directory.is_symlink():
            raise ValueError(
                f'Symbolic link not permitted: {directory}'
            )

        if directory.exists():
            if not directory.is_dir():
                raise ValueError(
                    f'Expected directory: {directory}'
                )

            info = directory.lstat()

            if hasattr(info, 'st_file_attributes'):
                reparse = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0)
                if info.st_file_attributes & reparse:
                    raise ValueError(
                        f'Reparse point not permitted: {directory}'
                    )

    return True



def _copy_local_source(source, descriptor):
    """Copy one stable, ordinary local file into an already-open staging descriptor."""
    source = Path(source)

    if source.is_symlink() or source.is_junction():
        raise ValueError('Local source cannot be a symbolic link or junction')

    before_path = source.lstat()
    reparse = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0)
    if getattr(before_path, 'st_file_attributes', 0) & reparse:
        raise ValueError('Local source cannot be a reparse point')
    if not stat.S_ISREG(before_path.st_mode):
        raise ValueError('Local source must be a regular file')
    if before_path.st_size <= 0:
        raise ValueError('Local source is empty')
    if before_path.st_size > MAX_BYTES:
        raise ValueError('Local source exceeds 80 MB safety limit')

    flags = os.O_RDONLY
    if hasattr(os, 'O_BINARY'):
        flags |= os.O_BINARY
    if hasattr(os, 'O_NOFOLLOW'):
        flags |= os.O_NOFOLLOW

    source_fd = os.open(str(source), flags)
    copied = 0
    staging_descriptor_owned = False
    try:
        opened = os.fstat(source_fd)
        if not stat.S_ISREG(opened.st_mode):
            raise ValueError('Opened local source is not a regular file')
        if getattr(opened, 'st_file_attributes', 0) & reparse:
            raise ValueError('Opened local source is a reparse point')

        def identity(info):
            # Windows lstat() and fstat() can expose
            # different st_ctime_ns values for the same file.
            # Retain stable identity and modification checks.
            return (
                info.st_dev, info.st_ino, info.st_size,
                info.st_mtime_ns, info.st_mode
            )

        if identity(before_path) != identity(opened):
            raise ValueError('Local source identity changed while opening')

        if opened.st_size > MAX_BYTES:
            raise ValueError('Local source exceeds 80 MB safety limit')

        digest = hashlib.sha256()
        destination = os.fdopen(descriptor, 'wb')
        staging_descriptor_owned = True
        with destination:
            while True:
                chunk = os.read(source_fd, 1024 * 1024)
                if not chunk:
                    break
                copied += len(chunk)
                if copied > MAX_BYTES:
                    raise ValueError('Local source exceeds 80 MB safety limit')
                digest.update(chunk)
                destination.write(chunk)

            destination.flush()
            os.fsync(destination.fileno())

        after_handle = os.fstat(source_fd)
        after_path = source.lstat()

        if identity(opened) != identity(after_handle):
            raise ValueError('Local source changed during staging')
        if identity(opened) != identity(after_path):
            raise ValueError('Local source pathname was replaced during staging')
        if copied != opened.st_size:
            raise ValueError('Local source size changed during staging')

        return copied, digest.hexdigest()
    finally:
        os.close(source_fd)
        if not staging_descriptor_owned:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _process_staged(
    row, root, delete_verified, audit_callback,
    stage_input, source_type, source_url='', source_path='',
    *, ocr_enabled=False
):
    if not isinstance(ocr_enabled, bool):
        raise TypeError('ocr_enabled must be a boolean')
    if delete_verified:
        raise ValueError(
            'Automatic attachment cleanup is disabled'
        )

    lic = safe_id(row['licitacion'].strip())
    filename = Path(row.get('filename', '').strip()).name
    if not filename or filename in ('.', '..'):
        filename = 'attachment'

    verify_work_directories(root)
    work = root / 'work'
    work.mkdir(parents=True, exist_ok=True)
    cache = root / 'cache' / lic
    verify_work_directories(root)

    if cache.is_symlink():
        raise ValueError('Unsafe licitacion cache directory')
    if cache.is_junction():
        raise ValueError('Junction not permitted in licitacion cache')
    if cache.exists() and not cache.is_dir():
        raise ValueError('Licitacion cache path is not a directory')

    audit = {
        'time': utc(), 'licitacion': lic, 'filename': filename,
        'url': source_url, 'source_type': source_type,
        'source_path': str(source_path) if source_path else '',
        'source_origin_url': row.get('source_origin_url', ''),
        'status': 'ERROR', 'sha256': '', 'bytes': '',
        'pages': '', 'segments': '', 'note': '', 'temporary_path': ''
    }

    work_identity = work.stat()
    fd, tempname = tempfile.mkstemp(
        prefix='mp_', suffix='.part', dir=work
    )
    temp = Path(tempname)
    identity = os.fstat(fd)
    audit['temporary_path'] = str(temp)

    try:
        staged_result = stage_input(temp, fd)
        audit['bytes'] = staged_result[0] if isinstance(staged_result, tuple) else staged_result
        digest = sha(temp)
        audit['sha256'] = digest

        if isinstance(staged_result, tuple) and len(staged_result) > 1:
            if staged_result[1] != digest:
                raise ValueError('Staged content SHA-256 differs from source SHA-256')

        output = cache / (
            digest + ('.ocr.json' if ocr_enabled else '.json')
        )
        if output.is_symlink() or output.is_junction():
            raise ValueError('Unsafe cache destination')
        if output.exists():
            existing = json.loads(output.read_text(encoding='utf-8'))
            if not (
                verified_cache(existing, digest)
                or verified_review_cache(existing, digest)
            ):
                raise ValueError(
                    'Existing cache incomplete or unverified; refusing cleanup'
                )
            if ocr_enabled and not any(
                s.get('method') == 'pdf_ocr'
                for s in existing.get('segments', [])
            ):
                raise ValueError(
                    'OCR sidecar has no OCR segments'
                )
            if ocr_enabled and not verified_review_cache(
                existing, digest
            ):
                raise ValueError(
                    'OCR sidecar must remain review-required'
                )
            audit['status'] = 'ALREADY_CACHED'
            audit['note'] = (
                'Existing review-required cache verified; temporary copy retained'
                if verified_review_cache(existing, digest)
                else 'Existing complete cache verified; temporary copy retained'
            )
            return audit

        segments, pages, hold = extract(
            temp, ocr_enabled=ocr_enabled
        )
        if ocr_enabled:
            if not any(
                s.get('method') == 'pdf_ocr'
                for s in segments
            ):
                audit['status'] = 'NO_OCR_RESULT'
                audit['note'] = (
                    'No OCR text recovered; staged copy retained'
                )
                return audit

        audit['pages'] = pages
        audit['segments'] = len(segments)

        record = {
            'source_name': filename,
            'source_url': source_url,
            'source_type': source_type,
            'source_origin_url': row.get('source_origin_url', ''),
            'source_path': str(source_path) if source_path else '',
            'licitacion': lic,
            'sha256': digest,
            'source_bytes': audit['bytes'],
            'pages': pages,
            'segments': segments,
            'errors': hold,
            'created_at': utc(),
            'extraction_status': (
                'REVIEW_REQUIRED' if hold else 'COMPLETE_TEXT_EXTRACTION'
            )
        }
        if ocr_enabled and not verified_review_cache(
            record, digest
        ):
            raise ValueError(
                'OCR review validation failed before publication'
            )
        atomic_json(output, record)
        check = json.loads(output.read_text(encoding='utf-8'))

        if check != record or check.get('sha256') != digest:
            raise ValueError(
                'Cache round-trip verification failed; temporary original retained'
            )

        if ocr_enabled and not verified_review_cache(
            check, digest
        ):
            raise ValueError(
                'OCR sidecar verification failed after publication'
            )

        if hold:
            if (
                check.get('extraction_status') != 'REVIEW_REQUIRED'
                or check.get('errors') != hold
                or not hold
            ):
                raise ValueError(
                    'Review cache validation failed; temporary original retained'
                )
        elif not verified_cache(check, digest):
            raise ValueError(
                'Cache completeness verification failed; temporary original retained'
            )

        if hold:
            audit['status'] = 'REVIEW_REQUIRED'
            audit['note'] = '; '.join(hold[:3])
        else:
            audit['status'] = 'VERIFIED_RETAINED'
            audit['note'] = (
                'Automatic cleanup disabled; temporary staging copy retained'
            )

        return audit
    except Exception as exc:
        audit['status'] = 'ERROR'
        audit['note'] = f'{type(exc).__name__}: {exc}'
        return audit
    finally:
        pass


def process(
    row, root, delete_verified, audit_callback=None,
    *, ocr_enabled=False
):
    if delete_verified:
        raise ValueError('Automatic attachment cleanup is disabled')
    url = row['url'].strip()
    if not allowed(url):
        raise ValueError('Untrusted URL')

    def stage(temp, descriptor):
        return download(url, temp, descriptor)

    return _process_staged(
        row, root, delete_verified, audit_callback,
        stage, 'url', source_url=url,
        ocr_enabled=ocr_enabled
    )


def process_local(
    row, root, delete_verified=False, audit_callback=None,
    *, ocr_enabled=False
):
    """Process an existing local attachment without deleting its source file."""
    if delete_verified:
        raise ValueError('Automatic attachment cleanup is disabled')
    source_value = row.get('source_path') or row.get('path')
    if not isinstance(source_value, str) or not source_value.strip():
        raise ValueError('Local manifest requires source_path')

    source = Path(source_value).expanduser()
    if not source.is_absolute():
        source = source.absolute()

    if source.is_symlink() or source.is_junction():
        raise ValueError('Local source cannot be a symbolic link or junction')

    if not source.is_file():
        raise ValueError('Local source file not found')

    root_path = Path(root).absolute()
    try:
        source_resolved = source.resolve(strict=True)
        root_resolved = root_path.resolve(strict=False)
        if source_resolved == root_resolved or root_resolved in source_resolved.parents:
            raise ValueError('Local source cannot be inside downloader root')
    except OSError as exc:
        raise ValueError(f'Unable to resolve local source: {exc}') from exc

    origin_url = row.get('source_origin_url', '').strip()
    if origin_url and not allowed(origin_url):
        raise ValueError('Untrusted licitacion origin URL')

    filename = row.get('filename', '').strip() or source.name
    local_row = dict(row)
    local_row['filename'] = filename

    def stage(temp, descriptor):
        return _copy_local_source(source, descriptor)

    return _process_staged(
        local_row, root, delete_verified, audit_callback,
        stage, 'playwright_local', source_url='',
        source_path=source_resolved,
        ocr_enabled=ocr_enabled
    )

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--manifest',type=Path,required=True,help='CSV columns: licitacion,filename,url,source_path (one source per row)')
    ap.add_argument('--root',type=Path,default=ROOT)
    ap.add_argument(
        '--delete-verified', action='store_true',
        help='Disabled legacy option; requests are rejected'
    )
    ap.add_argument(
        '--ocr', action='store_true',
        help='Enable Spanish OCR; cleanup prohibited'
    )
    args=ap.parse_args()
    if args.delete_verified:
        raise SystemExit(
            'STOP: Automatic attachment cleanup is disabled'
        )
    requested_root=args.root.absolute()

    # Inspect the supplied path before resolving redirections.
    if requested_root.is_symlink() or requested_root.is_junction():
        raise SystemExit('STOP: downloader root is a link or junction')

    production=(Path.home()/'Documents'/'Filtro_Grandes_Licitaciones').resolve()
    root=requested_root.resolve()

    if (
        root==production
        or production not in root.parents
        or not root.name.startswith('descarga_temporal')
    ):
        raise SystemExit(
            'STOP: root must be a dedicated descarga_temporal* folder '
            'inside the project'
        )

    # Reject existing redirected components within the project.
    current=production

    for component in root.relative_to(production).parts:
        current=current/component

        if current.is_symlink() or current.is_junction():
            raise SystemExit(
                f'STOP: redirected directory component: {current}'
            )
    if not args.manifest.is_file(): raise SystemExit('STOP: manifest not found')
    with args.manifest.open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f)
        columns = set(reader.fieldnames or [])
        if not {'licitacion', 'filename'} <= columns:
            raise SystemExit(
                'STOP: CSV requires licitacion and filename columns'
            )
        if not ({'url', 'source_path'} & columns):
            raise SystemExit(
                'STOP: CSV requires url or source_path column'
            )
        rows=list(reader)
    if not rows: raise SystemExit('STOP: empty manifest')
    if len(rows)>50: raise SystemExit('STOP: v1 pilot limit 50 attachments')
    root.mkdir(parents=True,exist_ok=True)
    print('TEMP DOWNLOADER v1.8 | automatic attachment deletion: DISABLED')
    print('Output:',root)
    audit_path=root/'audit.csv'
    fields=['time','licitacion','filename','url','source_type','source_path','source_origin_url','status','sha256','bytes','pages','segments','note','temporary_path']
    if audit_path.is_symlink() or audit_path.is_junction():
        raise SystemExit('STOP: audit.csv is a link or junction')

    with audit_path.open('a',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields)

        if f.tell()==0:
            writer.writeheader()
            f.flush()
            os.fsync(f.fileno())

        def durable_audit(record):
            writer.writerow(record)
            f.flush()
            os.fsync(f.fileno())

        for row in rows:
            try:
                url_value = (row.get('url') or '').strip()
                path_value = (row.get('source_path') or '').strip()

                if bool(url_value) == bool(path_value):
                    raise ValueError(
                        'Exactly one of url or source_path is required'
                    )

                if path_value:
                    result = process_local(
                        row,
                        root,
                        delete_verified=False,
                        audit_callback=durable_audit,
                        ocr_enabled=args.ocr
                    )
                else:
                    result = process(
                        row,
                        root,
                        delete_verified=False,
                        audit_callback=durable_audit,
                        ocr_enabled=args.ocr
                    )
            except Exception as exc:
                result = {k: '' for k in fields}
                result.update(
                    time=utc(),
                    licitacion=(row.get('licitacion') or ''),
                    filename=(row.get('filename') or ''),
                    url=(row.get('url') or ''),
                    source_path=(row.get('source_path') or ''),
                    source_origin_url=(
                        row.get('source_origin_url') or ''
                    ),
                    status='ERROR',
                    note=f'{type(exc).__name__}: {exc}'
                )

            durable_audit(result)
            print(
                result['licitacion'],
                result['status'],
                result['filename'],
                result['note'][:130]
            )
    print('Audit:',audit_path)

if __name__=='__main__': main()
