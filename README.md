# MRG Data Analysis

Intake desk for the 2026 Schneider Prize. Import a seven-column sample CSV, ask questions about it, or skip the questions and export the file.

The sheet columns are Sample ID, Date Sampled, Date Received, Machine, Component, Serial Number, and Reference Lube. Empty label fields stay empty in the export.

## Open it

```bash
python3 -m http.server 4173
```

Open http://127.0.0.1:4173

The page loads a generated week of 624 samples (2–7 Nov 2026), in the 500–700 samples-per-week range. That file is `data/output_example.csv`. It is not customer data. `data/output_empty.csv` is the header template.

## Use it

- Ask about machines, reference lubes, one intake day, missing serial numbers, or turnaround.
- Choose a day on the chart to pull that day’s rows into the sheet.
- Import a CSV with the prize headers, or with the label names Barcode, Date, Today's Date, Equip ID, Sample Point, SN, and Ref Lube. Extra columns are left out of the export.
- **Skip to submission** names the CSV and downloads it. Nothing is uploaded.

A sample ID that starts with `RN` is treated as a small tube. Every other ID is a large tube. Tube size is shown on the sheet and is not a column in the file.

## Checks

```bash
python3 scripts/generate_intake.py
node --test tests/desk.test.mjs
```

Regenerate the sample week only from `scripts/generate_intake.py`. It writes the CSV and `js/sample-week.js` together.
