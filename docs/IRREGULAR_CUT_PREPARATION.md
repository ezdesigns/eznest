# Small and self-crossing cut paths

The app's artwork-preserving PDF/AI import accepts finite small or self-crossing
cut paths without changing their vector commands, spot names, tint values or
print artwork. Strict `read_document(..., prepare=False)` keeps its existing
validation behavior.

`placementBoundary` is a conservative hull used only for ownership and nesting.
Original `commands` and `pdfPoints` remain the cutter instructions. Proven source
artwork groups can still become separate pieces with their complete paint and
bleed. If source grouping cannot prove ownership, `preservedPageGroup` reserves
the complete source crop and exports the entire original paint stream as one
group. It may use more material and is labeled “kept together.” It does not
silently repair cuts or guess which artwork to discard.

Both paths add preparation notes asking the operator to check the retained cuts.
This allows placement/export; it does not certify that a malformed source cut
will physically cut correctly. Nonfinite, oversized, clipped or out-of-page
cuts retain their existing safeguards. Existing duplicate and guide handling
is unchanged.

Regression coverage in `tests/test_irregular_cuts.py` checks self-crossings,
tiny/zero-length strokes, proven independent source groups, more than 200 cuts,
and out-of-page rejection. Import/export round trips compare cut commands,
spot definitions and tints, cut counts, and pixel-identical print/bleed renders.
These synthetic checks do not substitute for Illustrator, ONYX or a cutter test
of the reported customer file.
