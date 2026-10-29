# shop-connector-event/1

This is the only event shape the Shop Connector sends. Pairing uses the
existing OUTPUT pairing request from `output_pairing.py`. Delivery is one
POST per event to the existing telemetry path, with a stable `requestId`.

The connector does not upload Ez Nest's local proposal atoms directly. A
finished Ez Nest observation is wrapped as `nest.completed`. Its `payload`
is the `eznest-observation/1` projection from `telemetry_output.py`.

## Envelope

| Field | Meaning |
| --- | --- |
| schema | Always `shop-connector-event/1` |
| eventId | 64 lowercase hex characters. HMAC-SHA256 of the plug-in name, a newline, and the source line without its trailing newline, keyed by this install's salt. The same line on the same install always produces the same id. The salt stays on this computer. |
| requestId | UUIDv5 of `shop-connector:{instanceId}:{eventId}`. A retry sends this same id. OUTPUT already treats that as an idempotent receipt (`created` or `replay`). |
| source | `eznest`, `printer`, `cutter`, or `inventory` |
| instanceId | 32 lowercase hex characters, created once on this computer |
| occurredAt | UTC time from the log or view, `YYYY-MM-DDTHH:MM:SSZ`. Not a guessed clock time. |
| connectorVersion | Connector version, currently `0.1.0` |
| kind | `nest.completed`, `print.completed`, `cut.completed`, or `inventory.observed` |
| payload | Kind-specific object below. No extra keys. |

`eventId` is the line identity for this install. `requestId` is the POST
identity for this installation. Both are derived, not random, so a retry is
safe. The event id uses the same per-install salt as the other local hashes.

## Bands

Measurements use the bands in `docs/telemetry-contract.md`. A band is the
string `[lower,upper)`. Exact zero is `"0"`. Unknown is `null`.

| Measurement | Step |
| --- | --- |
| Roll or sheet length | 250 mm |
| Width and cut sizes (X and Y) | 100 mm |
| Thickness | 0.1 mm |
| Area | 0.25 m² (inside the Ez Nest projection) |
| Percent | 5 points, and only from 0 through 100 |
| Duration and print time | 15 seconds |
| Counts (copies, jobs, pieces, sheets) | 10 |
| Ink | 1 ml |
| Inventory quantity | 250 mm, 1 m, 1 ml, or 10 for sheets, rolls, and each |

These steps are the connector's reading of the telemetry contract. Ink,
thickness, and cut-size steps are not named in that document. They are
stated here so a shop can see the rounding. Exact values are not sent.

## Payloads

`print.completed` (source `printer`): `status` (`ok` or `abnormal`),
`printerClass`, `mediaClass`, `copiesBand`, `inkTotalMlBand`,
`inkChannelsMlBand`, `coveragePercentBand`, `printTimeSecondsBand`,
`widthMmBand`, `lengthMmBand`, `jobId`, `onyxStatus`, `machineModel`,
`mediaUsedFt`, `widthIn`, `axisSwapped`.

Print time, ink, and coverage keep those banded names. They are not exact
values. Status `1` is `ok`. Status `0` and `-1` are `abnormal`, and
`onyxStatus` repeats the raw code. The difference between `-1` and `0` is
not verified against ONYX documentation. Any other status is skipped.
`printerClass` and `machineModel` are the same coarse class (`epson_s80600`,
`roland_vs540`, `hp_latex_570`, `epson_7890`, or `unknown`). The raw model
string is not sent. `mediaClass` is one of `moto_regular`,
`moto_holographic`, `moto_chrome`, `custom`, `unknown`. The raw media profile
is not sent. `jobId` is a salted SHA-256 of the job title and source file
name. The salt stays on this computer.

`widthIn` and `mediaUsedFt` are inferred from the sample field positions:
width is the across-roll size in inches, and media used is length in inches
times copies divided by 12. They are rounded to hundredths. `axisSwapped` is
true when the logged across-roll size was above 64.5 inches and the axes were
exchanged. Those three values are inferred from samples, not from ONYX
documentation.

`cut.completed` (source `cutter`): `materialClass`, `thicknessMmBand`,
`jobCountBand`, `copiesBand`, `jobSizeXMmBand`, `jobSizeYMmBand`,
`copySizeXMmBand`, `copySizeYMmBand`, `durationSecondsBand`, `jobId`.

The Summa job name is the only field treated as a customer identity. `jobId`
is its salted SHA-256. The raw job name is not sent.

`inventory.observed` (source `inventory`): `materialClass`, `materialKey`,
`quantityBand`, `unit`, `reorderThresholdBand`, `source`.

`source` is always `view`. `materialKey` is a salted SHA-256 of the material
name. `unit` is `mm`, `m`, `ml`, `sheets`, `rolls`, or `each`. The event is
produced only when the on-hand quantity changes after the connect-time
baseline.

`nest.completed` (source `eznest`): the payload is the
`eznest-observation/1` object (`schema`, `requestId`, `kind`, `instanceId`,
`nestId`, `occurredAt`, `appVersion`, `materialClass`, `bands`). Job codes,
file names, and exact measurements are already removed by that projection.

## What is not a field

The allow-list is timing, material class, thickness, dimensions, counts,
status, and the banded ink and coverage figures above. The event has no
place for a job name, title, file name, customer name, phone, email,
address, price, cost, or order id. Printer preset names, Quick Set names,
print-mode text, raw media profile names, and IP addresses are not fields
either.

## JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "shop-connector-event/1",
  "title": "Shop Connector event",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema", "eventId", "requestId", "source", "instanceId", "occurredAt", "connectorVersion", "kind", "payload"],
  "properties": {
    "schema": {"const": "shop-connector-event/1"},
    "eventId": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    "requestId": {"type": "string", "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"},
    "source": {"enum": ["eznest", "printer", "cutter", "inventory"]},
    "instanceId": {"type": "string", "pattern": "^[0-9a-f]{32}$"},
    "occurredAt": {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"},
    "connectorVersion": {"type": "string", "pattern": "^[0-9]{1,5}\\.[0-9]{1,5}\\.[0-9]{1,5}$"},
    "kind": {"enum": ["nest.completed", "print.completed", "cut.completed", "inventory.observed"]},
    "payload": {"type": "object"}
  },
  "allOf": [
    {"if": {"properties": {"kind": {"const": "print.completed"}}, "required": ["kind"]}, "then": {"properties": {"source": {"const": "printer"}, "payload": {"$ref": "#/$defs/print"}}}},
    {"if": {"properties": {"kind": {"const": "cut.completed"}}, "required": ["kind"]}, "then": {"properties": {"source": {"const": "cutter"}, "payload": {"$ref": "#/$defs/cut"}}}},
    {"if": {"properties": {"kind": {"const": "inventory.observed"}}, "required": ["kind"]}, "then": {"properties": {"source": {"const": "inventory"}, "payload": {"$ref": "#/$defs/inventory"}}}},
    {"if": {"properties": {"kind": {"const": "nest.completed"}}, "required": ["kind"]}, "then": {"properties": {"source": {"const": "eznest"}, "payload": {"$ref": "#/$defs/nest"}}}}
  ],
  "$defs": {
    "band": {"type": ["string", "null"], "pattern": "^(?:0|\\[[0-9]+(?:\\.[0-9]+)?,[0-9]+(?:\\.[0-9]+)?\\))$"},
    "hash": {"type": ["string", "null"], "pattern": "^[0-9a-f]{64}$"},
    "material": {"enum": ["moto_regular", "moto_holographic", "moto_chrome", "custom", "unknown"]},
    "print": {
      "type": "object",
      "additionalProperties": false,
      "required": ["status", "printerClass", "mediaClass", "copiesBand", "inkTotalMlBand", "inkChannelsMlBand", "coveragePercentBand", "printTimeSecondsBand", "widthMmBand", "lengthMmBand", "jobId", "onyxStatus", "machineModel", "mediaUsedFt", "widthIn", "axisSwapped"],
      "properties": {
        "status": {"enum": ["ok", "abnormal"]},
        "printerClass": {"enum": ["epson_s80600", "roland_vs540", "hp_latex_570", "epson_7890", "unknown"]},
        "mediaClass": {"$ref": "#/$defs/material"},
        "copiesBand": {"$ref": "#/$defs/band"},
        "inkTotalMlBand": {"$ref": "#/$defs/band"},
        "inkChannelsMlBand": {"type": "object", "additionalProperties": {"$ref": "#/$defs/band"}},
        "coveragePercentBand": {"$ref": "#/$defs/band"},
        "printTimeSecondsBand": {"$ref": "#/$defs/band"},
        "widthMmBand": {"$ref": "#/$defs/band"},
        "lengthMmBand": {"$ref": "#/$defs/band"},
        "jobId": {"$ref": "#/$defs/hash"},
        "onyxStatus": {"enum": ["1", "-1", "0"]},
        "machineModel": {"enum": ["epson_s80600", "roland_vs540", "hp_latex_570", "epson_7890", "unknown"]},
        "mediaUsedFt": {"type": "string", "pattern": "^[0-9]+(?:\\.[0-9]{1,2})?$"},
        "widthIn": {"type": "string", "pattern": "^[0-9]+(?:\\.[0-9]{1,2})?$"},
        "axisSwapped": {"type": "boolean"}
      }
    },
    "cut": {
      "type": "object",
      "additionalProperties": false,
      "required": ["materialClass", "thicknessMmBand", "jobCountBand", "copiesBand", "jobSizeXMmBand", "jobSizeYMmBand", "copySizeXMmBand", "copySizeYMmBand", "durationSecondsBand", "jobId"],
      "properties": {
        "materialClass": {"$ref": "#/$defs/material"},
        "thicknessMmBand": {"$ref": "#/$defs/band"},
        "jobCountBand": {"$ref": "#/$defs/band"},
        "copiesBand": {"$ref": "#/$defs/band"},
        "jobSizeXMmBand": {"$ref": "#/$defs/band"},
        "jobSizeYMmBand": {"$ref": "#/$defs/band"},
        "copySizeXMmBand": {"$ref": "#/$defs/band"},
        "copySizeYMmBand": {"$ref": "#/$defs/band"},
        "durationSecondsBand": {"$ref": "#/$defs/band"},
        "jobId": {"$ref": "#/$defs/hash"}
      }
    },
    "inventory": {
      "type": "object",
      "additionalProperties": false,
      "required": ["materialClass", "materialKey", "quantityBand", "unit", "reorderThresholdBand", "source"],
      "properties": {
        "materialClass": {"$ref": "#/$defs/material"},
        "materialKey": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "quantityBand": {"$ref": "#/$defs/band"},
        "unit": {"enum": ["mm", "m", "ml", "sheets", "rolls", "each"]},
        "reorderThresholdBand": {"$ref": "#/$defs/band"},
        "source": {"const": "view"}
      }
    },
    "nest": {
      "type": "object",
      "additionalProperties": false,
      "required": ["schema", "requestId", "kind", "instanceId", "nestId", "occurredAt", "appVersion", "materialClass", "bands"],
      "properties": {
        "schema": {"const": "eznest-observation/1"},
        "requestId": {"type": "string"},
        "kind": {"type": "string"},
        "instanceId": {"type": "string"},
        "nestId": {"type": ["string", "null"]},
        "occurredAt": {"type": "string"},
        "appVersion": {"type": "string"},
        "materialClass": {"$ref": "#/$defs/material"},
        "bands": {"type": "object"}
      }
    }
  }
}
```

## Open questions

ONYX Thrive `JobLog.txt` lines are quoted fields separated by spaces inside
`{{ ... }}`. The positions used here come from shop samples and still need
confirming against one real JobLog line. Field `[6]` is treated as pixels
across the roll and `[5]` as pixels along the feed. A logged across-roll size
above 64.5 inches is treated as rotated and the axes are swapped. `widthIn`,
`mediaUsedFt`, and `machineModel` are inferred from those samples, not from
ONYX documentation. Status `1` is completed. `-1` and `0` are both abnormal;
which means aborted and which means incomplete is unverified. The end time is
epoch seconds. Values above 100 billion are treated as milliseconds.

Summa column order is confirmed. The time zone is not. Clocks are sent as
UTC. Size numbers are millimetres unless `sizeUnit` is `cm` or `in`. A comma
is treated as a decimal mark when the field has no dot.

OUTPUT does not yet document `shop-connector-event/1`. A live `--send` can
be rejected until that schema is registered. The dry run is the default.

Identical source lines collapse to one event. A replaced log file is treated
as a new connect and is not read back from the start.
