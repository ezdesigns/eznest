"""Preserve source cut names, color spaces and tint values in PDF exports."""
import hashlib
import io
import math

from pypdf import PdfWriter
from pypdf.generic import (ArrayObject, DictionaryObject, StreamObject, NameObject, ContentStream,
                           NumberObject, FloatObject, DecodedStreamObject)


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


def initial_color(space):
    space = space.get_object()
    kind = str(space[0]) if isinstance(space, list) else str(space)
    if kind == '/Separation': return [1.0]
    if kind == '/DeviceRGB': return [0.0] * 3
    if kind == '/DeviceCMYK': return [0.0, 0.0, 0.0, 1.0]
    if kind == '/ICCBased': return [0.0] * int(space[1].get_object()['/N'])
    if kind == '/Lab': return [0.0] * 3
    return [0.0]


def named_process_color(name, space, values):
    """An unnamed layer cut gets a cutter name, retaining its process color."""
    space = space.get_object()
    kind = str(space[0]) if isinstance(space, list) else str(space)
    count = {'/DeviceGray': 1, '/DeviceRGB': 3, '/DeviceCMYK': 4}.get(kind)
    if kind == '/ICCBased': count = int(space[1].get_object()['/N'])
    if count not in (1, 3, 4) or len(values) != count:
        raise ValueError('This cut color cannot be preserved. Use a named spot color in the source file.')
    white = [0] * count if count == 4 else [1] * count
    tint = DictionaryObject({NameObject('/FunctionType'): NumberObject(2),
        NameObject('/Domain'): ArrayObject([NumberObject(0), NumberObject(1)]),
        NameObject('/C0'): ArrayObject([FloatObject(v) for v in white]),
        NameObject('/C1'): ArrayObject([FloatObject(v) for v in values]),
        NameObject('/N'): NumberObject(1)})
    return ArrayObject([NameObject('/Separation'), NameObject('/'+name), space, tint])


class CutColors:
    """One color resource per source definition, never one per operation."""
    def __init__(self, documents, readers, mapping):
        self.spaces, self.paths, self._colors = {}, {}, {}
        self.names_by_operation = {}
        names, known, legacy, entries = {}, {}, {}, []
        for ident, (_, meta) in documents.items():
            reader = readers[ident]
            for piece in meta['pieces']:
                for cut in piece['cutPaths']:
                    source = cut.get('sourceColor')
                    name = cut.get('sourceSpot')
                    if source:
                        try:
                            space = reader.pages[cut['page']]['/Resources']['/ColorSpace'][source['resource']].get_object()
                            values = [float(v) for v in source['values']]
                        except (KeyError, IndexError, TypeError, ValueError):
                            raise ValueError('The original cut color is unavailable. Re-add the original file.') from None
                    elif name:
                        # Compatibility for stored jobs imported before color metadata.
                        cache_key = (ident, cut['page'], name)
                        if cache_key not in legacy:
                            page=reader.pages[cut['page']]
                            legacy[cache_key]=(self._legacy_space(page,name),self._legacy_tint(page,reader,name))
                        space, values = legacy[cache_key]
                    else:
                        raise ValueError('This older saved job does not include the original color of its unnamed cuts. Re-add the original file; no colors were changed.')
                    if not values or any(not math.isfinite(v) for v in values):
                        raise ValueError('Invalid source cut color values. Re-add the original file.')
                    original_spot = isinstance(space, list) and space[0] == '/Separation'
                    if original_spot:
                        if len(space) != 4 or len(values) != 1:
                            raise ValueError('Invalid source cut spot color.')
                        if name and str(space[1]).removeprefix('/') != name:
                            raise ValueError('The source cut name no longer matches its color. Re-add the original file.')
                    else:
                        if name:
                            raise ValueError('The original cut spot is unavailable. Re-add the original file.')
                        space = named_process_color(mapping['outputs'][cut['operation']]['spot'], space, values)
                        values = [1.0]
                    entries.append((ident,cut,space,values,original_spot))
        # Reserve every original name first. Newly named process cuts must not
        # override a source spot that happens to be encountered later.
        for ident,cut,space,values,original in entries:
            if not original: continue
            name = str(space[1]).removeprefix('/')
            signature = _signature(space[2:])
            if name in names and names[name] != signature:
                raise ValueError('Cut spot "'+name+'" has different color definitions in these files. Use matching spot definitions or nest the files separately; no colors were changed.')
            names[name] = signature
        for ident,cut,space,values,original in entries:
            name = str(space[1]).removeprefix('/')
            signature = _signature(space[2:])
            if not original:
                base,number=name,2
                while name in names and names[name] != signature:
                    name=base+'_'+str(number);number+=1
                space=ArrayObject([space[0],NameObject('/'+name),space[2],space[3]])
            names[name]=signature
            identity=(name,signature)
            if identity not in known:
                key='/EZCut'+(str(len(known)) if known else '')
                known[identity]=key;self.spaces[key]=space
            self.paths[(ident,cut['id'])]=(known[identity],values)
            self.names_by_operation.setdefault(cut['operation'],set()).add(name)

    @staticmethod
    def _legacy_tint(page, reader, name):
        # Older stores retained the color operators but not per-path tint
        # metadata. Recover a uniform tint; never guess among different tints.
        tints,visited=set(),set()
        def visit(stream,resources,inherited=(None,(0.0,)),depth=0):
            identity=(id(stream),inherited)
            if identity in visited:return
            if depth>16 or len(visited)>=10000:
                raise ValueError('Re-add the original file to preserve its cut tints.')
            visited.add(identity);state=inherited;stack=[]
            resources=resources.get_object()
            for args,op in ContentStream(stream,reader).operations:
                if op==b'q':stack.append(state)
                elif op==b'Q':state=stack.pop() if stack else inherited
                elif op==b'CS':
                    ref=resources.get('/ColorSpace',DictionaryObject()).get_object().get(args[0])
                    space=ref.get_object() if ref is not None else args[0]
                    spot=str(space[1]).removeprefix('/') if isinstance(space,list) and space[0]=='/Separation' else None
                    state=(spot,tuple(initial_color(space)))
                elif op in (b'SC',b'SCN'):
                    state=(state[0],tuple(float(v) for v in args if isinstance(v,(int,float))))
                elif op in (b'G',b'RG',b'K'):state=(None,tuple(map(float,args)))
                elif op in (b'n',b'S',b's',b'f',b'f*',b'F',b'B',b'B*',b'b',b'b*') and state[0]==name:
                    tints.add(state[1])
                elif op==b'Do':
                    ref=resources.get('/XObject',DictionaryObject()).get_object().get(args[0])
                    obj=ref.get_object() if ref is not None else None
                    if obj is not None and obj.get('/Subtype')=='/Form':
                        visit(obj,obj.get('/Resources',resources),state,depth+1)
        visit(page.get_contents(),page['/Resources'])
        if len(tints)>1:
            raise ValueError('This older saved job has different tints for cut spot "'+name+'". Re-add the original file to preserve each tint; no colors were changed.')
        return list(next(iter(tints))) if tints else [1.0]

    @staticmethod
    def _legacy_space(page, name):
        candidates, visited = {}, set()
        def visit(resources, depth=0):
            resources = resources.get_object()
            if id(resources) in visited: return
            if depth > 16 or len(visited) >= 10000:
                raise ValueError('Re-add the original file to preserve its cut colors.')
            visited.add(id(resources))
            for ref in resources.get('/ColorSpace', DictionaryObject()).get_object().values():
                color = ref.get_object()
                if isinstance(color, list) and len(color) == 4 and color[0] == '/Separation' and str(color[1]).removeprefix('/') == name:
                    candidates[_signature(color[2:])] = color
            for ref in resources.get('/XObject', DictionaryObject()).get_object().values():
                child = ref.get_object()
                if child.get('/Subtype') == '/Form' and '/Resources' in child:
                    visit(child['/Resources'], depth + 1)
        visit(page['/Resources'])
        if len(candidates) != 1:
            raise ValueError('The original color for cut spot "'+name+'" is missing or ambiguous. Re-add the original file; no colors were changed.')
        return next(iter(candidates.values()))

    def paint(self, ident, cut):
        key, values = self.paths[(ident, cut['id'])]
        return key+' CS '+' '.join(format(v, '.17g') for v in values)+' SCN'

    def preview_color(self, ident, cut):
        key, values = self.paths[(ident, cut['id'])]
        cache_key = (key, tuple(values))
        if cache_key not in self._colors:
            import pypdfium2 as pdfium
            writer = PdfWriter(); page = writer.add_blank_page(width=2, height=2)
            page[NameObject('/Resources')] = DictionaryObject({NameObject('/ColorSpace'): DictionaryObject({NameObject('/C'): self.spaces[key].clone(writer)})})
            stream = DecodedStreamObject()
            stream.set_data(('/C cs '+' '.join(format(v, '.17g') for v in values)+' scn 0 0 2 2 re f').encode('ascii'))
            page[NameObject('/Contents')] = writer._add_object(stream)
            raw = io.BytesIO(); writer.write(raw)
            with pdfium.PdfDocument(raw.getvalue()) as doc:
                p = doc[0]; bitmap = p.render(scale=2)
                try:
                    pixel = bitmap.to_pil().convert('RGB').getpixel((2, 2))
                finally:
                    bitmap.close(); p.close()
            self._colors[cache_key] = '#'+''.join(f'{v:02X}' for v in pixel)
        return self._colors[cache_key]
