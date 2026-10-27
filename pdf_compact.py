"""Lossless resource sharing for local PDFs with separately embedded repeats.

Reads a seekable file rather than first copying the entire upload into RAM.
Only identical encoded image streams AND their complete dictionaries/dependencies
are shared. No downsampling, recoloring, resizing or path edits occur here.
"""
import hashlib
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject, StreamObject, NameObject


def compact_pdf(source, destination):
    source, destination = Path(source), Path(destination)
    if source.resolve() == destination.resolve():
        raise ValueError('The original PDF must stay unchanged.')
    memo, active, canonical = {}, set(), {}
    stats = {'sharedImages': 0, 'uniqueImageBytes': 0, 'inputBytes': source.stat().st_size, 'editingPages': 0}
    with source.open('rb') as stream:
        reader = PdfReader(stream)
        if reader.is_encrypted:
            raise ValueError('Export an unencrypted print-only PDF.')
        if not 1 <= len(reader.pages) <= 25:
            raise ValueError('Use a PDF with 1 to 25 pages.')

        def fingerprint(value, depth=0):
            if depth > 64:
                return None
            ref = value if isinstance(value, IndirectObject) else getattr(value, 'indirect_reference', None)
            key = (ref.generation, ref.idnum) if ref is not None else None
            if key in memo:
                return memo[key]
            if key in active:
                return None  # Identity-dependent/cyclic resources stay separate.
            if key is not None:
                active.add(key)
            obj = value.get_object()
            digest = hashlib.sha256()
            digest.update(type(obj).__name__.encode('ascii'))
            shareable = True
            if isinstance(obj, DictionaryObject):
                # Identical optional-content names need not mean identical
                # visibility. Leave those resources for the normal import checks.
                if '/OC' in obj or obj.get('/Type') in ('/OCG', '/OCMD'):
                    shareable = False
                else:
                    for name in sorted(obj):
                        if name == '/Length':
                            continue
                        child = fingerprint(obj.raw_get(name), depth + 1)
                        if child is None:
                            shareable = False
                            break
                        digest.update(str(name).encode('utf-8') + b'\0' + child)
                if isinstance(obj, StreamObject):
                    digest.update(obj._data)
            elif isinstance(obj, ArrayObject):
                for item in obj:
                    child = fingerprint(item, depth + 1)
                    if child is None:
                        shareable = False
                        break
                    digest.update(child)
            else:
                digest.update(repr(obj).encode('utf-8'))
            result = digest.digest() if shareable else None
            if key is not None:
                active.discard(key)
                memo[key] = result
            if result is not None and isinstance(obj, StreamObject) and obj.get('/Subtype') == '/Image':
                first = canonical.get(result)
                if first is None:
                    canonical[result] = obj
                    stats['uniqueImageBytes'] += len(obj._data)
                    if stats['uniqueImageBytes'] > 512_000_000:
                        raise ValueError('This PDF has more than 512 MB of distinct embedded images. Export fewer designs per file without repeating them.')
                elif key is not None and obj is not first:
                    # pypdf 6.19 caches every resolved stream. Alias duplicates
                    # here so neither its reader nor writer retains N copies.
                    # Do not use cache_indirect_object: it changes the retained
                    # object's own indirect_reference. Covered by alias tests.
                    reader.resolved_objects[key] = first
                    stats['sharedImages'] += 1
            return result

        seen_resources = set()

        def scan(resources, depth=0):
            if depth > 32:
                raise ValueError('PDF forms are nested too deeply.')
            resources = resources.get_object()
            identity = id(resources)
            if identity in seen_resources:
                return
            seen_resources.add(identity)
            objects = resources.get('/XObject', {}).get_object() if '/XObject' in resources else {}
            for ref in objects.values():
                obj = ref.get_object()
                if obj.get('/Subtype') == '/Image':
                    fingerprint(ref)
                elif obj.get('/Subtype') == '/Form' and '/Resources' in obj:
                    scan(obj['/Resources'], depth + 1)

        for page in reader.pages:
            scan(page['/Resources'])
        writer = PdfWriter()
        for page in reader.pages:
            if '/PieceInfo' in page:
                stats['editingPages'] += 1
            # Illustrator's private editing data is not printable PDF content.
            # This is the same exclusion used by read_document, done before a
            # multi-gigabyte file is copied into memory. Keep the source on disk.
            writer.add_page(page, excluded_keys=['/PieceInfo', '/Thumb'])
        for name in ('/OCProperties', '/OutputIntents'):
            if name in reader.root_object:
                writer.root_object[NameObject(name)] = reader.root_object[name].clone(writer)
        with destination.open('xb') as output:
            writer.write(output)
    stats['outputBytes'] = destination.stat().st_size
    return stats
