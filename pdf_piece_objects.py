"""Identify complete PDF painting operations without cropping their artwork.

This does not rewrite PDFium's interpretation back into the output. Temporary
marked content links conservative paint envelopes to original PDF operators;
the output retains those original operators and their original resources.
"""
import ctypes
import io
import uuid

from pypdf import PdfWriter
from pypdf.generic import (ContentStream, DecodedStreamObject, DictionaryObject,
                           NameObject, NumberObject)
from shapely.ops import unary_union

PATH_PAINT = set(b'S s f F f* B B* b b*'.split())
OTHER_PAINT = {b'Do', b'sh', b'INLINE IMAGE'}
MAX_SOURCE_BYTES = 8_000_000


def analyze_objects(page, reader, diagnostics=None):
    """Return None when complete-object ownership cannot be established."""
    import pypdfium2 as pdfium
    import pypdfium2.raw as api
    from artwork_bounds import paint_envelopes
    data = page.get_contents().get_data()
    if diagnostics is not None:
        diagnostics['contentBytes'] = len(data)
    if len(data) > MAX_SOURCE_BYTES:
        return None
    operations = ContentStream(page.get_contents(), reader).operations
    # A clipping text run can affect artwork after ET. Keep the existing path
    # for those files until text clipping has its own ownership analysis.
    if any(op == b'Tr' and int(values[0]) >= 4 for values, op in operations):
        return None
    mark_name = 'EZPiece' + uuid.uuid4().hex
    spans, tagged, index = [], [], 0
    while index < len(operations):
        values, op = operations[index]
        end = index
        if op == b'BT':
            while end < len(operations) and operations[end][1] != b'ET':
                end += 1
            if end == len(operations):
                return None
        elif op not in PATH_PAINT | OTHER_PAINT:
            tagged.append((values, op)); index += 1; continue
        ident = len(spans)
        spans.append((index, end, op))
        tagged.append(([NameObject('/' + mark_name), DictionaryObject({NameObject('/id'): NumberObject(ident)})], b'BDC'))
        tagged.extend(operations[index:end+1])
        tagged.append(([], b'EMC'))
        index = end + 1
    if not spans:
        return None
    temporary = PdfWriter()
    annotated = temporary.add_page(page)
    stream = ContentStream(None, None); stream.operations = tagged
    encoded = DecodedStreamObject(); encoded.set_data(stream.get_data())
    annotated[NameObject('/Contents')] = temporary._add_object(encoded.flate_encode())
    raw = io.BytesIO(); temporary.write(raw)
    seen = set()

    def label_for(obj):
        found = []
        for n in range(api.FPDFPageObj_CountMarks(obj)):
            mark = api.FPDFPageObj_GetMark(obj, n)
            size = ctypes.c_ulong()
            if not api.FPDFPageObjMark_GetName(mark, None, 0, size) or size.value > 4096:
                continue
            buffer = (ctypes.c_ushort * ((size.value+1)//2))()
            if not api.FPDFPageObjMark_GetName(mark, buffer, size.value, size):
                continue
            name = ctypes.string_at(buffer, size.value).decode('utf-16-le').rstrip('\0')
            if name == mark_name:
                value = ctypes.c_long()
                if not api.FPDFPageObjMark_GetParamIntValue(mark, b'id', value):
                    raise ValueError('Could not identify a PDF artwork object.')
                found.append(value.value)
        if len(found) != 1 or not 0 <= found[0] < len(spans):
            raise ValueError('PDF artwork ownership could not be proved.')
        seen.add(found[0])
        return found[0]

    shapes = {}
    with pdfium.PdfDocument(raw.getvalue()) as doc:
        annotated_page = doc[0]
        try:
            for label, shape in paint_envelopes(annotated_page, label_for=label_for):
                shapes.setdefault(label, []).append(shape)
        finally:
            annotated_page.close()
    # PDFium can optimize away empty paint operations. Until those are proven
    # empty independently, retain the established clipped export for that page.
    if seen != set(range(len(spans))):
        if diagnostics is not None:
            diagnostics.update(total=len(spans), seen=sorted(seen), missing=[(i, spans[i][2].decode()) for i in range(len(spans)) if i not in seen])
        return None
    return operations, spans, {i: unary_union(shapes.get(i, [])) for i in seen}


def select_objects(analyzed, envelope):
    """Select whole paint objects only; never slice a crossing object."""
    if analyzed is None:
        return None
    from pdf_export_forms import remove_empty_groups
    operations, spans, shapes = analyzed
    rejected = set()
    for ident, shape in shapes.items():
        if shape.is_empty or envelope.disjoint(shape):
            rejected.add(ident)
        elif not envelope.covers(shape):
            return None
    starts = {start: (i, end, op) for i, (start, end, op) in enumerate(spans)}
    # Remove the unused geometry as well as its paint. Paths are not graphics
    # state: q/Q must not reset this tracking. Preserve any path used by W/W*.
    discarded_paths, pending_paths, pending_clip = set(), [], False
    for index, (values, op) in enumerate(operations):
        if op in (b'm', b'l', b'c', b'v', b'y', b'h', b're'):
            pending_paths.append(index)
        elif op in (b'W', b'W*'):
            pending_clip = True
        elif op in PATH_PAINT or op == b'n':
            span = starts.get(index)
            if not pending_clip and (op == b'n' or span is not None and span[0] in rejected):
                discarded_paths.update(pending_paths)
            pending_paths, pending_clip = [], False
    result, index, kept = [], 0, 0
    while index < len(operations):
        if index in discarded_paths:
            index += 1
            continue
        span = starts.get(index)
        if span is not None and span[0] in rejected:
            if span[2] in PATH_PAINT:
                # Consuming the path still applies any pending W/W* clipping.
                result.append(([], b'n'))
            index = span[1] + 1
            continue
        if span is not None:
            kept += 1
        result.append(operations[index]); index += 1
    stream = ContentStream(None, None)
    stream.operations = remove_empty_groups(result)
    return stream.get_data(), {'sourceObjects': len(spans), 'pieceObjects': kept}
