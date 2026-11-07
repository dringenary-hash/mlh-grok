import { COLUMNS } from "./columns.js";

const SHORT_MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

export function isBlank(value) {
  return String(value ?? "").trim() === "";
}

export function parseDate(value) {
  if (isBlank(value)) return null;
  const text = String(value).trim();
  let match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text);
  if (match) return utcDate(match[1], match[2], match[3]);
  match = /^(\d{1,2})\/(\d{1,2})\/(\d{4})$/.exec(text);
  if (match) return utcDate(match[3], match[1], match[2]);
  return null;
}

function utcDate(year, month, day) {
  const y = Number(year);
  const m = Number(month);
  const d = Number(day);
  const date = new Date(Date.UTC(y, m - 1, d));
  if (
    date.getUTCFullYear() !== y ||
    date.getUTCMonth() !== m - 1 ||
    date.getUTCDate() !== d
  ) {
    return null;
  }
  return date;
}

export function isoFromDate(date) {
  return date.toISOString().slice(0, 10);
}

export function formatDate(date) {
  return `${WEEKDAYS[date.getUTCDay()]} ${date.getUTCDate()} ${SHORT_MONTHS[date.getUTCMonth()]} ${date.getUTCFullYear()}`;
}

export function sampleClass(row) {
  const id = String(row["Sample ID"] ?? "").trim();
  if (/^RN\b/i.test(id)) return "small";
  if (id) return "large";
  return "unknown";
}

export function turnaroundDays(row) {
  const sampled = parseDate(row["Date Sampled"]);
  const received = parseDate(row["Date Received"]);
  if (!sampled || !received) return null;
  return Math.round((received.getTime() - sampled.getTime()) / 86400000);
}

function tally(rows, column, { blanks = false } = {}) {
  const counts = new Map();
  for (const row of rows) {
    const value = String(row[column] ?? "").trim();
    if (!value && !blanks) continue;
    const key = value || "(blank)";
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return [...counts.entries()]
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
}

export function analyze(rows) {
  const list = rows ?? [];
  let large = 0;
  let small = 0;
  let unknown = 0;
  let missingSerial = 0;
  let missingSerialLarge = 0;
  let missingSerialSmall = 0;
  let blankMachine = 0;
  let blankLube = 0;
  let negativeTurnaround = 0;
  let over7 = 0;
  const turnarounds = [];
  const dayCounts = new Map();
  const idCounts = new Map();
  const blankByColumn = {};

  for (const field of COLUMNS) blankByColumn[field] = 0;

  for (const row of list) {
    const kind = sampleClass(row);
    if (kind === "large") large += 1;
    else if (kind === "small") small += 1;
    else unknown += 1;

    for (const field of COLUMNS) {
      if (isBlank(row[field])) blankByColumn[field] += 1;
    }
    if (isBlank(row["Serial Number"])) {
      missingSerial += 1;
      if (kind === "large") missingSerialLarge += 1;
      if (kind === "small") missingSerialSmall += 1;
    }
    if (isBlank(row.Machine)) blankMachine += 1;
    if (isBlank(row["Reference Lube"])) blankLube += 1;

    const days = turnaroundDays(row);
    if (days != null) {
      turnarounds.push(days);
      if (days < 0) negativeTurnaround += 1;
      if (days >= 7) over7 += 1;
    }

    const received = parseDate(row["Date Received"]);
    const dayKey = received ? isoFromDate(received) : "";
    dayCounts.set(dayKey, (dayCounts.get(dayKey) ?? 0) + 1);

    const id = String(row["Sample ID"] ?? "").trim();
    if (id) idCounts.set(id, (idCounts.get(id) ?? 0) + 1);
  }

  const byDay = [...dayCounts.entries()]
    .map(([iso, count]) => ({
      iso,
      label: iso ? formatDate(parseDate(iso)) : "No date received",
      count,
    }))
    .sort((a, b) => a.iso.localeCompare(b.iso));

  const datedDays = byDay.filter((day) => day.iso);
  const busiestDay = datedDays.reduce(
    (best, day) => (best == null || day.count > best.count ? day : best),
    null,
  );

  const duplicateIds = [...idCounts.entries()]
    .filter(([, count]) => count > 1)
    .map(([id, count]) => ({ id, count }))
    .sort((a, b) => b.count - a.count || a.id.localeCompare(b.id));

  const topMachines = tally(list, "Machine").slice(0, 5);
  const topLubes = tally(list, "Reference Lube").slice(0, 5);
  const topComponents = tally(list, "Component").slice(0, 5);
  const sortedTurnaround = [...turnarounds].sort((a, b) => a - b);
  const medianTurnaround = sortedTurnaround.length
    ? sortedTurnaround[Math.floor((sortedTurnaround.length - 1) / 2)]
    : null;

  return {
    count: list.length,
    large,
    small,
    unknown,
    byDay,
    busiestDay,
    receivedStart: datedDays[0] ?? null,
    receivedEnd: datedDays[datedDays.length - 1] ?? null,
    topMachines,
    topLubes,
    topComponents,
    namedMachines: tally(list, "Machine").length,
    blankMachine,
    blankLube,
    missingSerial,
    missingSerialLarge,
    missingSerialSmall,
    medianTurnaround,
    turnaroundCount: turnarounds.length,
    over7,
    negativeTurnaround,
    duplicateIds,
    blankByColumn,
  };
}

export function namedValues(rows, column) {
  return [
    ...new Set(
      rows
        .map((row) => String(row[column] ?? "").trim())
        .filter((value) => value !== ""),
    ),
  ];
}

export function rowsWhere(rows, predicate) {
  return rows.filter(predicate);
}
