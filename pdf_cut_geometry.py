"""Placement geometry is separate from the original cutter instructions."""
from shapely.geometry import Polygon, box


def nesting_boundary(path):
    return Polygon(path.get('placementBoundary', path['pdfPoints']))


def preserve_page_group(page, paths):
    """Reserve the source crop when piece ownership cannot be proved.

    Keep all visible paint and bleed; do not infer ownership or repair cuts.
    """
    from cut_mapping import counts
    from pdf_io import MM
    envelope = box(*map(float, page.cropbox))
    x0, y0, x1, y1 = envelope.bounds
    piece = dict(paths[0])
    piece.update(preservedPageGroup=True, cutPaths=paths, sourcePieceCount=1,
                 anchor=[x0, y1], bounds=[x0, y0, x1, y1],
                 points=[[(x-x0)*MM, (y1-y)*MM] for x,y in envelope.exterior.coords[:-1]],
                 clipCommands=[('m', list(envelope.exterior.coords[0]))]+
                              [('l', list(p)) for p in envelope.exterior.coords[1:]]+[('h', [])])
    piece['cutCounts'] = counts(piece)
    return [piece]
