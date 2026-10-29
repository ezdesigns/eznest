"""Conservative XObject pruning for repeated clipped PDF artwork.

Never modify source drawing commands, images, masks, or color resources. A Do
may be omitted only when its entire transformed paint box misses the export
clip's bounding box. Unknown extents stay in the output.
"""
import math
from pypdf.generic import ContentStream, DictionaryObject, NameObject


def invocation_bounds(page, reader):
    from pdf_io import IDENTITY, matrix, point
    content = ContentStream(page.get_contents(), reader)
    resources = page['/Resources']
    xobjects = resources.get('/XObject', DictionaryObject()).get_object()
    current = IDENTITY
    stack = []
    bounds = {}
    for index, (operands, op) in enumerate(content.operations):
        if op == b'q':
            stack.append(current)
        elif op == b'Q':
            current = stack.pop() if stack else IDENTITY
        elif op == b'cm':
            current = matrix(current, tuple(map(float, operands)))
        elif op == b'Do':
            obj = xobjects.get(operands[0])
            if obj is None:
                continue
            obj = obj.get_object()
            local = current
            if obj.get('/Subtype') == '/Image':
                rect = (0, 0, 1, 1)
            elif obj.get('/Subtype') == '/Form' and '/BBox' in obj:
                rect = tuple(map(float, obj['/BBox']))
                local = matrix(current, tuple(map(float, obj.get('/Matrix', IDENTITY))))
            else:
                continue
            if len(rect) != 4 or not all(math.isfinite(v) for v in (*rect, *local)):
                continue
            x0, y0, x1, y1 = rect
            points = [point(local, (x, y)) for x, y in ((x0,y0),(x1,y0),(x0,y1),(x1,y1))]
            bounds[index] = (min(p[0] for p in points), min(p[1] for p in points),
                             max(p[0] for p in points), max(p[1] for p in points))
    return content.operations, bounds


def clipped_commands(operations, bounds, clip):
    """Keep all state/path/text operations; prune only provably invisible Do's."""
    x0, y0, x1, y1 = clip
    kept = []
    names = set()
    for index, (operands, op) in enumerate(operations):
        if op == b'Do':
            extent = bounds.get(index)
            # A small extra tolerance keeps touching/interpolated boundary cases.
            if extent is not None:
                a, b, c, d = extent
                if c < x0 - .02 or a > x1 + .02 or d < y0 - .02 or b > y1 + .02:
                    continue
            names.add(operands[0])
        kept.append((operands, op))
    stream = ContentStream(None, None)
    stream.operations = remove_empty_groups(kept)
    return stream.get_data(), names


def remove_empty_groups(operations):
    """Drop balanced state-only groups after pruning, never uncertain operators.

    PDF paths are NOT saved by q/Q. Only drop groups entered and left with an
    empty current path; otherwise the path may still be used outside the group.
    Text matrices, marked content, and every painting operator remain untouched.
    """
    harmless = set(b'cm gs w J j M d ri i CS cs SC SCN sc scn G g RG rg K k TL '
                   b'm l c v y h re W W* n'.split())
    paths = set(b'm l c v y h re'.split())
    finishes = set(b'n S s f F f* B B* b b*'.split())
    output = []
    stack = []
    path_open = False
    for entry in operations:
        op = entry[1]
        if op == b'q':
            stack.append([len(output), path_open, True])
        elif op == b'Q' and stack:
            start, had_path, safe = stack.pop()
            if safe and not had_path and not path_open:
                del output[start:]
                continue
            if stack:
                stack[-1][2] = False
        elif stack and op not in harmless:
            stack[-1][2] = False
        if op in paths:
            path_open = True
        elif op in finishes:
            path_open = False
        output.append(entry)
    return output


def piece_form(page, writer, analyzed, clip):
    from pdf_io import form_from_page
    content, names = clipped_commands(*analyzed, clip)
    resources = DictionaryObject(page['/Resources'])
    if '/XObject' in resources:
        original = resources['/XObject']
        fonts = resources.get('/Font', DictionaryObject()).get_object()
        if any(font.get_object().get('/Subtype') == '/Type3' for font in fonts.values()):
            # Glyph streams can resolve images from the page without a top-level Do.
            # Keep the enclosing scope when those indirect consumers may exist.
            names = set(original)
        for name in names:
            obj = original[name]
            if obj.get('/Subtype') == '/Form':
                own = obj.get('/Resources')
                own = own.get_object() if own is not None else None
                # Retained child Forms can use this enclosing XObject scope.
                # Top-level Do names alone cannot prove those resources unused.
                if not isinstance(own, DictionaryObject) or '/XObject' not in own:
                    names = set(original)
                    break
        resources[NameObject('/XObject')] = DictionaryObject({name: original.raw_get(name) for name in names})
    return form_from_page(page, writer, content=content, resources=resources)


def clip_bounds(commands):
    # Bézier control points enclose the complete curve. Unknown commands retain
    # the original page form instead of guessing at a smaller region.
    points = []
    for op, values in commands:
        if op == 'h':
            continue
        if op not in ('m', 'l', 'c') or len(values) % 2:
            return None
        points.extend(zip(values[::2], values[1::2]))
    if not points or not all(math.isfinite(float(v)) for p in points for v in p):
        return None
    return (min(p[0] for p in points), min(p[1] for p in points),
            max(p[0] for p in points), max(p[1] for p in points))
