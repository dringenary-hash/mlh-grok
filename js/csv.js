import { COLUMNS } from "./columns.js";

const ALIASES = {
  "Sample ID": ["sample id", "sampleid", "barcode", "barcode or num"],
  "Date Sampled": ["date sampled", "sampled date", "date"],
  "Date Received": ["date received", "received date", "todays date"],
  Machine: ["machine", "equip id", "equipment", "equipment id"],
  Component: ["component", "sample point"],
  "Serial Number": ["serial number", "serial", "sn"],
  "Reference Lube": ["reference lube", "ref lube", "lube", "lubricant"],
};

export function normalizeHeader(value) {
  return String(value ?? "")
    .trim()
    .toLowerCase()
    .replace(/['’]/g, "")
    .replace(/[^a-z0-9]+/g, " ")
    .trim()
    .replace(/\s+/g, " ");
}

export function parseCsv(text) {
  const source = String(text ?? "")
    .replace(/^\uFEFF/, "")
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n");
  const matrix = [];
  let row = [];
  let cell = "";
  let quoted = false;

  for (let index = 0; index < source.length; index += 1) {
    const char = source[index];
    if (quoted) {
      if (char === '"') {
        if (source[index + 1] === '"') {
          cell += '"';
          index += 1;
        } else {
          quoted = false;
        }
      } else {
        cell += char;
      }
      continue;
    }
    if (char === '"') {
      quoted = true;
      continue;
    }
    if (char === ",") {
      row.push(cell);
      cell = "";
      continue;
    }
    if (char === "\n") {
      row.push(cell);
      matrix.push(row);
      row = [];
      cell = "";
      continue;
    }
    cell += char;
  }

  if (cell.length > 0 || row.length > 0) {
    row.push(cell);
    matrix.push(row);
  }

  return matrix.filter((line, lineIndex) => {
    if (lineIndex === 0) return line.some((value) => String(value).trim() !== "");
    return line.some((value) => String(value).trim() !== "");
  });
}

function fieldForHeader(header) {
  const key = normalizeHeader(header);
  if (!key) return null;
  for (const field of COLUMNS) {
    if (normalizeHeader(field) === key) return field;
  }
  for (const field of COLUMNS) {
    if (ALIASES[field].includes(key)) return field;
  }
  return null;
}

export function inspectTable(matrix) {
  if (!matrix.length) {
    return { error: "That file has no header row." };
  }
  const headers = matrix[0].map((header) => String(header ?? "").trim());
  const mapping = {};
  const conflicts = [];
  const extras = [];

  headers.forEach((header, index) => {
    const field = fieldForHeader(header);
    if (!field) {
      if (header) extras.push(header);
      return;
    }
    if (mapping[field] != null) {
      conflicts.push(field);
      return;
    }
    mapping[field] = index;
  });

  const missing = COLUMNS.filter((field) => mapping[field] == null);
  return { headers, mapping, missing, extras, conflicts, matrix };
}

export function rowsFromMapping(matrix, mapping) {
  const body = matrix.slice(1);
  return body
    .filter((row) => row.some((value) => String(value ?? "").trim() !== ""))
    .map((row) => {
      const record = {};
      for (const field of COLUMNS) {
        const index = mapping[field];
        record[field] = index == null ? "" : String(row[index] ?? "").trim();
      }
      return record;
    });
}

export function readTable(text) {
  const matrix = parseCsv(text);
  const inspected = inspectTable(matrix);
  if (inspected.error) return inspected;
  const ready =
    inspected.missing.length === 0 && inspected.conflicts.length === 0;
  return {
    ...inspected,
    ready,
    rows: ready ? rowsFromMapping(matrix, inspected.mapping) : [],
  };
}

function escapeCell(value) {
  const text = value == null ? "" : String(value);
  if (/[",\n]/.test(text)) return `"${text.replace(/"/g, '""')}"`;
  return text;
}

export function toCsv(rows) {
  const lines = [COLUMNS.join(",")];
  for (const row of rows) {
    lines.push(COLUMNS.map((field) => escapeCell(row[field] ?? "")).join(","));
  }
  return `${lines.join("\n")}\n`;
}

export function safeFileName(value) {
  const cleaned = String(value ?? "")
    .trim()
    .replace(/[/\\?%*:|"<>]/g, "")
    .replace(/\s+/g, "-")
    .replace(/^\.+/, "");
  if (!cleaned || cleaned === ".csv") return "";
  return cleaned.toLowerCase().endsWith(".csv") ? cleaned : `${cleaned}.csv`;
}
