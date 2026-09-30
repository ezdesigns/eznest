# Mixed cut-workflow milestone — 0.12

Recorded 2026-09-30 from the shop's supplied recon summary and a review of the
eznest importer. The generic mixed-operation workflow below is now implemented
and covered by synthetic tests. Reported shop names remain unverified starter
aliases, not a certified active shop preset. The recon files and matched production
originals have not yet been inspected in this task.

## Reported shop evidence

The reported workflow is Illustrator -> ONYX -> GoProduce -> Summa F1612.

| Reported string in cut/config files | Reported role | Reported selection |
| --- | --- | --- |
| LNRegmark | Registration | SP99 |
| LNThru-cut | Through cut / drag knife | SP9 |
| LNKiss-cut | Kiss cut | SP4 |
| CutContour_Kiss-cut | ONYX cut-path layer | Not yet independently checked |

These strings and selections are shop-specific observations, not universal
defaults. Inspect the actual cut-file syntax before deciding whether LN is part
of a literal name or a command prefix. Preserve the raw strings separately from
parsed layer names and tool selections. Do not turn SP selections into universal
physical tool-slot assumptions.

Exact spot-color names in the Illustrator/PDF artwork remain pending. A downstream
cut-layer name does not by itself establish a source PDF layer or spot name.
The presence of both cut types in the same piece is a reported requirement; a
matched live example remains to be checked.

The shop reports an 11-piece Kawasaki proof of concept at kawi-render/nest/ with
paley-413-nest-print.pdf. That relative location was not found in this task workspace
or the inspected recent task folders. It is not evidence that eznest 0.11 passed
that kit. Preserve the matched AI, print PDF and cut file outside source control
when their full paths arrive.

Material fallback to Vinyl + Kiss-cut, manual tool selection, and manual registration
placement are hypotheses from the recon, not confirmed operator steps. Do not change
material defaults or cutter settings from those hypotheses.

## Vendor documentation cross-check

ONYX documents creation of separate cut layers from separate spot-color names,
with matching cut settings assigned by name:
[Using CUT-Server](https://onyxgfx.com/wp-content/uploads/2023/03/Using-CUT-Server.pdf).
Its Quick Sets can recognize configured spot-name prefixes:
[Creating Quick Sets](https://help.onyxgfx.com/24/ONYXGo/Content/RIP-Queue/Quick%20Sets/Creating%20Quick%20Sets.htm).

GoProduce documents separating PDF/DXF methods by layer name, spot-color name or
color: [GoProduce manual, Import Job](https://www.summa.com/media/qmldhzza/goproduce2_rev005_en.pdf).
These sources describe capabilities; they do not verify the shop's active settings.

Accordingly, model source path identity, source spot, source layer, ONYX cut-layer
mapping, and downstream method/tool selection separately. Do not require every shop
to encode both a spot and a layer, or assume one plain CutContour spot distinguishes
two methods in every RIP configuration.

## Implemented in 0.12

The importer records an outer packing boundary separately from each owned cut
path, including source layer/spot, exact curve commands and resolved operation.
Contained interior closed/open cuts no longer become independent pieces. Both
layer-only and spot-only classification work, with explicit conflict errors.
One rigid transform moves artwork and all cuts through copies, rotations and
whole-piece sheet splitting. Output has one configured spot and layer per type.
Known old registration paint is stripped; ONYX/finishing owns new sheet marks.

Output profile contains shareable matching rules and output names. Generic paths
require an operator choice in the UI unless a rule resolves them. Existing API
clients omitting cutMapping retain generic-contour behavior for compatibility;
this does not silently assign a thru/kiss method. Old active PDF imports require
re-import because metadata modelVersion 2 stores the complete cut model.

The review screen, layout details, CSV checklist and JSON manifest show cut counts.
No SP commands are generated. Starter output names need matching RIP settings.
Unknown marks inside ordinary art and separate nested pieces are not inferred.

## Model and behavior contract

1. A piece owns its artwork references, nesting boundary, bleed allowance, and a
   list of cut paths. Each path retains a stable ID, original geometry, source
   spot/layer and resolved operation (thru, kiss or explicitly unresolved/custom).
   Apply one placement transform to the complete piece. Interior cuts must not
   become independent nested pieces. An operation path need not itself be a
   closed packing boundary; preserve valid interior/open cuts where the workflow
   supports them.
2. Determine ownership from supported explicit grouping or an unambiguous boundary
   relationship. Do not assign a path to the nearest piece by guesswork. If multiple
   pieces could own it, require a review or reject the import with an explanation.
3. Keep nesting geometry distinct from cutting instructions. Use a validated piece
   boundary/envelope containing its required art, bleed and cuts. A kiss-only piece
   must still be nestable; do not require a thru-cut perimeter in every design.
4. Store configurable matching rules by exact spot/layer and explicit prefixes, with
   documented precedence and visible conflicts. Generic CutContour without enough
   information remains unresolved, rather than silently becoming kiss or thru.
5. Export separately named cut separations/layers according to the selected shop's
   mapping. Strip each extracted cut from copied print content before re-emitting
   it once. Preserve original curves and operation identity through rotation,
   copies and sheet splitting. Confirm ONYX recognizes the distinct output methods;
   separate PDF layer names alone are not proof of that.
6. Registration belongs to the sheet/RIP workflow. It must not become a nestable
   piece, be duplicated with each copy, or retain old sheet coordinates after a
   new nest. Existing marks need explicit detection/handling; ONYX remains the
   intended owner of newly generated marks in this shop's reported workflow.
7. Keep setup in a shareable shop preset. Normal use remains add files, confirm
   width/quantities, nest, review and export. Show detected thru/kiss counts and
   unresolved paths in review details. Expose mapping controls only when needed.

## Acceptance evidence

- Synthetic mixed-operation fixtures: two pieces, distinct thru perimeters,
  multiple kiss paths, repeated forms, rotated copies, nested boundaries, conflicts,
  missing spot/layer names, and sheet-level registration data.
- Export/re-import preserves piece counts and per-operation path counts, curve
  geometry, ownership and shared transforms. No duplicate cut paths remain in
  the print content. Neither sheet splitting nor filler changes ownership.
- Matched shop AI/PDF/cut set: inspect exact names and formats, classify every
  source path, compare original/rendered/exported geometry at actual size, and
  confirm the expected 11 pieces only if that is what the supplied source contains.
- ONYX/GoProduce read-only preview confirms method mapping and registration before
  a separately operated physical print/cut trial. Never dispatch the cutter from
  this validation step.

The immediate priority is preserving every piece and its cut operations correctly.
Shop-specific speed/material priorities can then be ranked from actual operator
steps and equal-settings comparisons. Hardware models are not an MVP onboarding gate.
