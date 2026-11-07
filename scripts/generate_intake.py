#!/usr/bin/env python3
"""Build a one-week intake file from the Schneider Prize column template.

Columns, in prize order:
  Sample ID, Date Sampled, Date Received, Machine, Component,
  Serial Number, Reference Lube.

Large tubes follow the large-label guide: barcode or Num, Date, the
intake date, Equip ID, Sample Point, a blank serial, and Ref Lube.
Small tubes follow the small-label guide: an RN with the circled
number and GS or NGS, the intake date, and an SN. Machine, component,
and reference lube stay blank because that guide does not list them.

Counts are fixed. The seed only shuffles row order.
"""

from __future__ import annotations

import csv
import json
import random
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COLUMNS = [
    "Sample ID",
    "Date Sampled",
    "Date Received",
    "Machine",
    "Component",
    "Serial Number",
    "Reference Lube",
]

DAY_QUOTAS = [
    ("2026-11-02", 150),
    ("2026-11-03", 128),
    ("2026-11-04", 112),
    ("2026-11-05", 121),
    ("2026-11-06", 96),
    ("2026-11-07", 17),
]

MACHINES = [
    "C-101 Conveyor Gearbox",
    "C-104 Conveyor Pulley",
    "P-201 Boiler Feed Pump",
    "P-210 Sump Pump",
    "F-301 ID Fan",
    "F-310 Cooling Tower Fan",
    "M-401 Mill Motor",
    "G-510 Ball Mill Gearbox",
    "CR-701 Crusher",
    "B-601 Bucket Elevator",
    "HY-901 Hydraulic Power Unit",
    "RD-120 Rotary Dryer",
    "EX-160 Extruder Gearbox",
    "MX-170 Mixer",
    "CP-180 Compressor",
    "AG-801 Agitator",
]

LUBES = [
    "Mobilgrease XHP 222",
    "Mobilith SHC 220",
    "Shell Gadus S3 V220C",
    "Shell Gadus S2 V100 2",
    "Chevron Ulti-Plex Grease EP",
    "Fuchs Renolit HI-TEMP 2",
    "Kluberplex BEM 41-132",
    "Castrol Tribol GR 100-2 PD",
]

COMPONENTS = [
    "DE Bearing",
    "NDE Bearing",
    "Input Shaft",
    "Output Shaft",
    "Motor Inboard",
    "Motor Outboard",
    "Open Gear",
    "Thrust Bearing",
    "Coupling Guard",
    "Pillow Block",
]

LARGE_COUNT = 406
SMALL_COUNT = 218
C101 = MACHINES[0]
TOP_LUBE = LUBES[0]
C101_COUNT = 72
TOP_LUBE_COUNT = 140
BLANK_LUBE_LARGE = 20
BLANK_MACHINE_LARGE = 5
SLOW_COUNT = 30
NEGATIVE_COUNT = 6
BLANK_SAMPLED_LARGE = 8
SMALL_MISSING_SERIAL = 12


def shift(iso: str, days: int) -> str:
    year, month, day = (int(part) for part in iso.split("-"))
    return (date(year, month, day) + timedelta(days=days)).isoformat()


def weighted(rng: random.Random, items: list[str]) -> str:
    weights = list(range(len(items), 0, -1))
    return rng.choices(items, weights=weights, k=1)[0]


def build() -> list[dict[str, str]]:
    rng = random.Random(20261102)
    dates: list[str] = []
    for iso, count in DAY_QUOTAS:
        dates.extend([iso] * count)
    rng.shuffle(dates)

    other_machines = MACHINES[1:]
    other_lubes = LUBES[1:]
    rows: list[dict[str, str]] = []

    for index, received in enumerate(dates):
        if index < LARGE_COUNT:
            rows.append(large_row(rng, index, received, other_machines, other_lubes))
        else:
            rows.append(small_row(index, received))

    large_rows = [row for row in rows if not row["Sample ID"].startswith("RN")]
    for source, copy in ((0, 10), (1, 11), (2, 12)):
        large_rows[copy]["Sample ID"] = large_rows[source]["Sample ID"]

    rng.shuffle(rows)
    check(rows)
    return rows


def large_row(
    rng: random.Random,
    index: int,
    received: str,
    other_machines: list[str],
    other_lubes: list[str],
) -> dict[str, str]:
    if index < C101_COUNT:
        machine = C101
    elif index < C101_COUNT + BLANK_MACHINE_LARGE:
        machine = ""
    else:
        machine = weighted(rng, other_machines)

    if index < TOP_LUBE_COUNT:
        lube = TOP_LUBE
    elif index < TOP_LUBE_COUNT + BLANK_LUBE_LARGE:
        lube = ""
    else:
        lube = weighted(rng, other_lubes)

    if 180 <= index < 180 + NEGATIVE_COUNT:
        sampled = shift(received, 2)
    elif 200 <= index < 200 + SLOW_COUNT:
        sampled = shift(received, -10)
    elif 190 <= index < 190 + BLANK_SAMPLED_LARGE:
        sampled = ""
    else:
        sampled = shift(received, -(index % 5))

    if 100 <= index < 140:
        sample_id = f"N-{7000 + index}"
    else:
        sample_id = f"{10000000 + index:08d}"

    return {
        "Sample ID": sample_id,
        "Date Sampled": sampled,
        "Date Received": received,
        "Machine": machine,
        "Component": weighted(rng, COMPONENTS),
        "Serial Number": "",
        "Reference Lube": lube,
    }


def small_row(index: int, received: str) -> dict[str, str]:
    offset = index - LARGE_COUNT
    mark = "NGS" if offset % 5 == 0 else "GS"
    serial = "" if offset < SMALL_MISSING_SERIAL else f"SN{800000 + offset}"
    return {
        "Sample ID": f"RN-{3000 + offset} {mark}",
        "Date Sampled": shift(received, -(offset % 4)),
        "Date Received": received,
        "Machine": "",
        "Component": "",
        "Serial Number": serial,
        "Reference Lube": "",
    }


def check(rows: list[dict[str, str]]) -> None:
    if len(rows) != LARGE_COUNT + SMALL_COUNT:
        raise SystemExit(f"expected 624 rows, got {len(rows)}")
    if sum(count for _, count in DAY_QUOTAS) != len(rows):
        raise SystemExit("day quotas do not add up to the row count")

    large = [row for row in rows if not row["Sample ID"].startswith("RN")]
    small = [row for row in rows if row["Sample ID"].startswith("RN")]
    if len(large) != LARGE_COUNT or len(small) != SMALL_COUNT:
        raise SystemExit("large/small split changed")

    c101 = sum(1 for row in rows if row["Machine"] == C101)
    if c101 != C101_COUNT:
        raise SystemExit(f"expected {C101_COUNT} rows for {C101}, got {c101}")

    named: dict[str, int] = {}
    for row in rows:
        if row["Machine"]:
            named[row["Machine"]] = named.get(row["Machine"], 0) + 1
    busiest = max(named.values())
    if busiest != C101_COUNT or named[C101] != busiest:
        raise SystemExit("C-101 is no longer the unique busiest machine")

    top_lube = sum(1 for row in rows if row["Reference Lube"] == TOP_LUBE)
    if top_lube != TOP_LUBE_COUNT:
        raise SystemExit(f"expected {TOP_LUBE_COUNT} rows of {TOP_LUBE}")

    missing_serial_small = [
        row for row in small if row["Serial Number"] == ""
    ]
    if len(missing_serial_small) != SMALL_MISSING_SERIAL:
        raise SystemExit("small-tube blank serial count changed")
    if any(row["Serial Number"] for row in large):
        raise SystemExit("large tubes should leave serial blank")
    if any(row["Machine"] or row["Component"] or row["Reference Lube"] for row in small):
        raise SystemExit("small tubes should leave machine, component, and lube blank")


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    rows = build()
    data_dir = ROOT / "data"
    js_dir = ROOT / "js"
    data_dir.mkdir(exist_ok=True)
    js_dir.mkdir(exist_ok=True)

    example = data_dir / "output_example.csv"
    empty = data_dir / "output_empty.csv"
    write_csv(example, rows)
    write_csv(empty, [])

    csv_text = example.read_text(encoding="utf-8")
    module = (
        "export const SAMPLE_WEEK_CSV = "
        + json.dumps(csv_text)
        + ";\nexport const SAMPLE_WEEK_LABEL = "
        + json.dumps("Sample week of 2–7 Nov 2026")
        + ";\n"
    )
    (js_dir / "sample-week.js").write_text(module, encoding="utf-8")
    print(f"Wrote {len(rows)} samples to {example.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
