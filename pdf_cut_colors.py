"""Keep a cut spot's source appearance without changing its output name.

If mixed files disagree or use unnamed process cuts, the output uses the
standard operation color. Never guess which shop's spot definition wins.
"""
import hashlib

from pypdf.generic import DictionaryObject, StreamObject


def _signature(value, depth=0):
    if depth > 12:
        raise ValueError('Color resource nesting is too deep')
    value = value.get_object() if hasattr(value, 'get_object') else value
    if isinstance(value, DictionaryObject):
        result = tuple((str(k), _signature(v, depth + 1)) for k, v in sorted(value.items())
                       if k not in ('/Length', '/Filter', '/DecodeParms'))
        if isinstance(value, StreamObject):
            result += (('stream', hashlib.sha256(value.get_data()).hexdigest()),)
        return result
    if isinstance(value, list):
        return tuple(_signature(v, depth + 1) for v in value)
    return str(value)


def source_cut_colors(documents, readers):
    """Return unmodified Separation definitions when every source agrees."""
    candidates, required, found, uncertain = {}, set(), set(), set()
    for ident, (_, meta) in documents.items():
        names = {}
        for piece in meta['pieces']:
            for cut in piece['cutPaths']:
                operation, name = cut['operation'], cut.get('sourceSpot')
                if not name:
                    uncertain.add(operation)
                else:
                    names.setdefault(name, set()).add(operation)
                    required.add((ident, operation, name))
        visited = set()

        def visit(resources, depth=0):
            resources = resources.get_object()
            if id(resources) in visited:
                return
            if depth > 15 or len(visited) >= 10000:
                uncertain.update(op for ops in names.values() for op in ops)
                return
            visited.add(id(resources))
            for ref in resources.get('/ColorSpace', DictionaryObject()).get_object().values():
                color = ref.get_object()
                if not isinstance(color, list) or len(color) != 4 or color[0] != '/Separation':
                    continue
                name = str(color[1]).removeprefix('/')
                for op in names.get(name, []):
                    try:
                        signature = _signature(color[2:])
                    except (ValueError, TypeError, RecursionError):
                        uncertain.add(op)
                        continue
                    candidates.setdefault(op, {})[signature] = color
                    found.add((ident, op, name))
            for ref in resources.get('/XObject', DictionaryObject()).get_object().values():
                child = ref.get_object()
                if child.get('/Subtype') == '/Form' and '/Resources' in child:
                    visit(child['/Resources'], depth + 1)

        for page in readers[ident].pages:
            visit(page['/Resources'])
    uncertain.update(op for _, op, _ in required - found)
    return {op: next(iter(choices.values())) for op, choices in candidates.items()
            if len(choices) == 1 and op not in uncertain}
