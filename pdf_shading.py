"""Equivalent solid paint for constant axial shadings Illustrator cannot edit.

Real gradients, profiles, transparency and clipping are retained. Only an
unbounded, fully extended axial shading with a provably constant Type 2
function is eligible; uncertain cases retain the original PDF operators.
"""
import math

from pypdf.generic import (ContentStream, DictionaryObject, FloatObject,
                           NameObject, DecodedStreamObject)


def constant_color(shading):
    try:
        if shading.get('/ShadingType') != 2 or any(k in shading for k in ('/BBox', '/Background')):
            return None
        if list(shading.get('/Extend', [])) != [True, True]:
            return None
        coords = list(map(float, shading['/Coords']))
        if len(coords) != 4 or coords[:2] == coords[2:] or not all(map(math.isfinite, coords)):
            return None
        fn = shading['/Function']
        if fn.get('/FunctionType') != 2:
            return None
        a, b = list(fn['/C0']), list(fn['/C1'])
        if not a or a != b or not all(math.isfinite(float(v)) for v in a):
            return None
        if not math.isfinite(float(fn['/N'])) or float(fn['/N']) <= 0:
            return None
        # Keep bounded functions and nonstandard domains unchanged.
        if '/Range' in fn or list(fn.get('/Domain', [])) != [0, 1] or list(shading.get('/Domain', [0, 1])) != [0, 1]:
            return None
        return a
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def solid_shadings(content, resources, bbox):
    """Return new content/resources without mutating either source object."""
    from pdf_io import IDENTITY, matrix, point
    if b'sh' not in content:
        return content, resources
    shades = resources.get('/Shading', DictionaryObject()).get_object()
    eligible = {name: (shade.get_object(), constant_color(shade.get_object()))
                for name, shade in shades.items()}
    eligible = {name: value for name, value in eligible.items() if value[1] is not None}
    if not eligible:
        return content, resources
    # Glyph programs and Forms may inherit this resource scope. Keep these
    # unusual scopes untouched rather than remove a shading they still use.
    fonts = resources.get('/Font', DictionaryObject()).get_object()
    if any(font.get_object().get('/Subtype') == '/Type3' for font in fonts.values()):
        return content, resources
    objects = resources.get('/XObject', DictionaryObject()).get_object()
    if any(obj.get_object().get('/Subtype') == '/Form' for obj in objects.values()):
        return content, resources
    original_resources = resources
    resources = DictionaryObject(resources)
    colors = DictionaryObject(resources.get('/ColorSpace', DictionaryObject()).get_object())
    resources[NameObject('/ColorSpace')] = colors
    stream = ContentStream(None, None)
    stream.set_data(content)
    result, stack, current, path_open = [], [], IDENTITY, False
    replaced = set()
    x0, y0, x1, y1 = map(float, bbox)
    for values, op in stream.operations:
        if op == b'q':
            stack.append(current)
        elif op == b'Q':
            current = stack.pop() if stack else IDENTITY
        elif op == b'cm':
            current = matrix(current, tuple(map(float, values)))
        elif op in (b'm', b'l', b'c', b'v', b'y', b'h', b're'):
            path_open = True
        elif op in (b'n', b'S', b's', b'f', b'F', b'f*', b'B', b'B*', b'b', b'b*'):
            path_open = False
        if op == b'sh' and values[0] in eligible and not path_open:
            a, b, c, d, e, f = current
            det = a*d-b*c
            if math.isfinite(det) and abs(det) > 1e-12:
                inverse = (d/det, -b/det, -c/det, a/det, (c*f-d*e)/det, (b*e-a*f)/det)
                corners = [point(inverse, p) for p in ((x0,y0),(x1,y0),(x1,y1),(x0,y1))]
                if all(math.isfinite(v) for p in corners for v in p):
                    shade, color = eligible[values[0]]
                    name = NameObject('/EZSolidShading' + str(len(colors)))
                    while name in colors:
                        name = NameObject(str(name) + '_')
                    colors[name] = shade.raw_get('/ColorSpace')
                    result.extend([([], b'q'), ([name], b'cs'), (color, b'scn')])
                    result.extend(([FloatObject(v) for v in p], b'm' if i == 0 else b'l') for i,p in enumerate(corners))
                    result.extend([([], b'h'), ([], b'f'), ([], b'Q')])
                    replaced.add(values[0])
                    continue
        result.append((values, op))
    if not replaced:
        return content, original_resources
    used = {values[0] for values, op in result if op == b'sh'}
    # Illustrator parses even unused shading resources. Remove a replaced
    # definition only after proving no remaining operator can reference it.
    resources[NameObject('/Shading')] = DictionaryObject(
        {name: shade for name, shade in shades.items() if name not in replaced or name in used})
    stream.operations = result
    return stream.get_data(), resources


def compatible_forms(resources, writer):
    """Normalize leaf Forms in the writer's cloned resources, once per Form.

    The cache also prevents recursion on cyclic resource graphs. Original PDF
    objects belong to a different reader and are never modified here.
    """
    cache = getattr(writer, '_eznest_shading_forms', None)
    if cache is None:
        cache = writer._eznest_shading_forms = {}
    objects = resources.get('/XObject', DictionaryObject()).get_object()
    for name, ref in list(objects.items()):
        obj = ref.get_object()
        if obj.get('/Subtype') != '/Form' or '/Resources' not in obj or '/BBox' not in obj:
            continue
        key = id(obj)
        if key in cache:
            objects[name] = cache[key]
            continue
        cache[key] = ref
        child_resources = obj['/Resources']
        compatible_forms(child_resources, writer)
        original = obj.get_data()
        data, child_resources = solid_shadings(original, child_resources, obj['/BBox'])
        if data == original:
            continue
        replacement = DecodedStreamObject()
        replacement.set_data(data)
        replacement.update({k:v for k,v in obj.items() if k not in ('/Length', '/Filter', '/DecodeParms')})
        replacement[NameObject('/Resources')] = child_resources
        cache[key] = writer._add_object(replacement.flate_encode())
        objects[name] = cache[key]
