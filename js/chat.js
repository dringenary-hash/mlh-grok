import {
  analyze,
  formatDate,
  isoFromDate,
  namedValues,
  parseDate,
  rowsWhere,
  sampleClass,
  turnaroundDays,
} from "./analyze.js";

const MONTHS = {
  january: 1,
  jan: 1,
  february: 2,
  feb: 2,
  march: 3,
  mar: 3,
  april: 4,
  apr: 4,
  may: 5,
  june: 6,
  jun: 6,
  july: 7,
  jul: 7,
  august: 8,
  aug: 8,
  september: 9,
  sep: 9,
  sept: 9,
  october: 10,
  oct: 10,
  november: 11,
  nov: 11,
  december: 12,
  dec: 12,
};

const MONTH_PATTERN =
  "january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec";

export function starterQuestions(rows) {
  const report = analyze(rows);
  const day = report.busiestDay
    ? report.busiestDay.label
    : "4 Nov 2026";
  return [
    "Find patterns in this file",
    "Which machines sent the most samples?",
    "How many samples are missing a serial number?",
    "What is the turnaround from sampled to received?",
    "Which reference lubes show up most?",
    `Samples received on ${day}`,
  ];
}

export function interpret(message, rows) {
  const list = rows ?? [];
  const raw = String(message ?? "").trim();
  const q = raw.toLowerCase().replace(/\s+/g, " ");
  if (!raw) {
    return keep(list, "Type a question about this file, or skip to submission.", [
      "Questions use the seven columns already on the sheet.",
    ]);
  }
  if (/^(help|what can i ask|what can you)\b/.test(q)) return helpReply(list);
  if (/\b(show all|show every|clear the filter|clear filter|every sample)\b/.test(q)) {
    return {
      summary: `Showing all ${count(list.length)}.`,
      lines: [],
      rows: list,
      filterLabel: null,
      highlightDay: null,
      suggestions: starterQuestions(list).slice(0, 3),
      action: null,
    };
  }
  if (
    /\b(skip to submission|submit the file|export the (csv|file)|download the (csv|file))\b/.test(
      q,
    )
  ) {
    return {
      summary: "Opening submission so you can name and download the CSV.",
      lines: ["The download is the full intake file, including rows hidden by a question."],
      rows: null,
      keep: true,
      filterLabel: null,
      highlightDay: null,
      suggestions: [],
      action: "submit",
    };
  }

  const report = analyze(list);

  if (/\bduplicat/.test(q)) return duplicateReply(list, report);
  if (isSampledAfter(q)) return sampledAfterReply(list, report);
  if (isTurnaround(q)) return turnaroundReply(list, report, q);
  if (isMissing(q) || /\b(incomplete|gaps)\b/.test(q)) {
    const reply = missingReply(list, report, q);
    if (reply) return reply;
  }

  const when = findDate(q);
  if (when && !isTurnaround(q)) return dateReply(list, q, when);

  const lube = matchNamed(q, namedValues(list, "Reference Lube"));
  if (lube && !wantsLubeRank(q)) return lubeReply(list, report, lube);

  const machine = matchMachine(q, namedValues(list, "Machine"));
  if (machine && !wantsMachineRank(q)) return machineReply(list, report, machine);
  if (/\bbusiest machine\b/.test(q) && report.topMachines[0]) {
    return machineReply(list, report, report.topMachines[0].name);
  }

  if (wantsLubeRank(q)) return lubeRankReply(report, list);
  if (wantsMachineRank(q)) return machineRankReply(report, list);
  if (wantsComponentRank(q)) return componentRankReply(report, list);
  if (/\bsmall\b/.test(q) && /\b(tube|sample|label)s?\b/.test(q)) {
    return classReply(list, "small");
  }
  if (/\blarge\b/.test(q) && /\b(tube|sample|label)s?\b/.test(q)) {
    return classReply(list, "large");
  }
  if (/\bpatterns?\b|\boverview\b|\bbriefing\b|\bwhat stands out\b/.test(q)) {
    return patternReply(list, report);
  }
  if (/\bhow many\b|\bcount\b|\bvolume\b|\bhow big\b/.test(q)) {
    return {
      summary: `${count(list.length)} are in this file.`,
      lines: splitLine(report),
      rows: list,
      filterLabel: null,
      highlightDay: null,
      suggestions: starterQuestions(list).slice(1, 4),
      action: null,
    };
  }
  return helpReply(list);
}

function helpReply(rows) {
  return keep(
    rows,
    "I can answer from the seven columns in this file.",
    [
      "Ask for patterns, a machine, a reference lube, samples received on a date, missing serial numbers, or the turnaround from Date Sampled to Date Received.",
    ],
    starterQuestions(rows).slice(0, 4),
  );
}

function patternReply(rows, report) {
  if (!report.count) {
    return keep(rows, "This file has no samples yet.", [
      "Import a CSV, or load the sample week.",
    ]);
  }
  const lines = [splitLine(report)];
  if (report.busiestDay) {
    lines.push(
      `Busiest intake day is ${report.busiestDay.label} with ${count(report.busiestDay.count)}.`,
    );
  }
  if (report.topMachines[0]) {
    lines.push(
      `Busiest machine is ${report.topMachines[0].name} with ${count(report.topMachines[0].count)}. ${count(report.blankMachine)} leave Machine blank.`,
    );
  }
  if (report.topLubes[0]) {
    lines.push(
      `Most common reference lube is ${report.topLubes[0].name} with ${count(report.topLubes[0].count)}. ${count(report.blankLube)} leave Reference Lube blank.`,
    );
  }
  lines.push(serialLine(report));
  if (report.medianTurnaround != null) {
    lines.push(turnaroundLine(report));
  }
  if (report.duplicateIds.length) {
    lines.push(
      `${count(report.duplicateIds.length, "sample ID is repeated", "sample IDs are repeated")}.`,
    );
  }
  const suggestions = ["Show small tubes missing a serial number"];
  if (report.topMachines[0]) {
    suggestions.unshift(`Show samples for ${report.topMachines[0].name}`);
  }
  if (report.over7) suggestions.push("Show samples with a turnaround of 7 days or more");
  return {
    summary: "Patterns in this file",
    lines,
    rows,
    filterLabel: null,
    highlightDay: null,
    suggestions,
    action: null,
  };
}

function machineRankReply(report, rows) {
  if (!report.topMachines.length) {
    return keep(rows, "No row names a machine.", [
      `${count(report.blankMachine)} leave Machine blank.`,
    ]);
  }
  return {
    summary: `${report.topMachines[0].name} sent the most samples.`,
    lines: [
      ...report.topMachines.map(
        (item, index) => `${index + 1}. ${item.name}: ${count(item.count)}`,
      ),
      `${count(report.blankMachine)} leave Machine blank, mostly small tubes.`,
    ],
    rows,
    filterLabel: null,
    highlightDay: null,
    suggestions: [`Show samples for ${report.topMachines[0].name}`],
    action: null,
  };
}

function lubeRankReply(report, rows) {
  if (!report.topLubes.length) {
    return keep(rows, "No row names a reference lube.", [
      `${count(report.blankLube)} leave Reference Lube blank.`,
    ]);
  }
  return {
    summary: `${report.topLubes[0].name} is the most common reference lube.`,
    lines: report.topLubes.map(
      (item, index) => `${index + 1}. ${item.name}: ${count(item.count)}`,
    ),
    rows,
    filterLabel: null,
    highlightDay: null,
    suggestions: [`Show samples with ${report.topLubes[0].name}`],
    action: null,
  };
}

function componentRankReply(report, rows) {
  if (!report.topComponents.length) {
    return keep(rows, "No row names a component.", []);
  }
  return {
    summary: `${report.topComponents[0].name} is the most common component.`,
    lines: report.topComponents.map(
      (item, index) => `${index + 1}. ${item.name}: ${count(item.count)}`,
    ),
    rows,
    filterLabel: null,
    highlightDay: null,
    suggestions: [],
    action: null,
  };
}

function machineReply(rows, report, name) {
  const matched = rowsWhere(rows, (row) => row.Machine === name);
  const rank = report.topMachines.findIndex((item) => item.name === name);
  const lubes = mix(matched, "Reference Lube");
  const lines = [];
  if (rank >= 0) lines.push(`That is named machine ${rank + 1} by sample count.`);
  if (lubes[0]) lines.push(`Reference lube on these rows: ${lubes[0].name} (${lubes[0].count}).`);
  return {
    summary: `${count(matched.length)} ${matched.length === 1 ? "is" : "are"} for ${name}.`,
    lines,
    rows: matched,
    filterLabel: `Machine · ${name}`,
    highlightDay: null,
    suggestions: ["Which machines sent the most samples?", "Show every sample"],
    action: null,
  };
}

function lubeReply(rows, report, name) {
  const matched = rowsWhere(rows, (row) => row["Reference Lube"] === name);
  const machines = mix(matched, "Machine");
  const lines = [];
  if (machines[0] && machines[0].name !== "(blank)") {
    lines.push(`Most of these name ${machines[0].name} (${machines[0].count}).`);
  }
  return {
    summary: `${count(matched.length)} use ${name}.`,
    lines,
    rows: matched,
    filterLabel: `Reference Lube · ${name}`,
    highlightDay: null,
    suggestions: ["Which reference lubes show up most?", "Show every sample"],
    action: null,
  };
}

function dateReply(rows, q, when) {
  const field = /\bsampled\b/.test(q) && !/\breceived\b/.test(q)
    ? "Date Sampled"
    : "Date Received";
  const matched = rowsWhere(rows, (row) => {
    const date = parseDate(row[field]);
    return date != null && isoFromDate(date) === when.iso;
  });
  const label = formatDate(when.date);
  return {
    summary: `${count(matched.length)} have ${field} of ${label}.`,
    lines: [],
    rows: matched,
    filterLabel: `${field} · ${label}`,
    highlightDay: field === "Date Received" ? when.iso : null,
    suggestions: ["Show every sample", "Find patterns in this file"],
    action: null,
  };
}

function missingReply(rows, report, q) {
  const field = missingField(q);
  const overview = /\bfields\b|\bincomplete\b|\bgaps\b/.test(q);
  if (!field || overview) {
    return {
      summary: "Blank cells by column",
      lines: Object.entries(report.blankByColumn).map(
        ([name, value]) => `${name}: ${count(value, "blank", "blanks")}`,
      ),
      rows,
      filterLabel: null,
      highlightDay: null,
      suggestions: ["How many samples are missing a serial number?"],
      action: null,
    };
  }
  if (field === "Serial Number") {
    const onlySmall = /\bsmall\b/.test(q);
    const onlyLarge = /\blarge\b/.test(q) && !onlySmall;
    const matched = rowsWhere(rows, (row) => {
      if (String(row["Serial Number"] ?? "").trim() !== "") return false;
      if (onlySmall) return sampleClass(row) === "small";
      if (onlyLarge) return sampleClass(row) === "large";
      return true;
    });
    const label = onlySmall
      ? "Small tubes missing a serial number"
      : onlyLarge
        ? "Large tubes missing a serial number"
        : "Missing serial number";
    return {
      summary: `${count(matched.length)} have no serial number.`,
      lines: [serialLine(report)],
      rows: matched,
      filterLabel: label,
      highlightDay: null,
      suggestions: onlySmall
        ? ["Show every sample"]
        : ["Show small tubes missing a serial number", "Show every sample"],
      action: null,
    };
  }

  const matched = rowsWhere(rows, (row) => String(row[field] ?? "").trim() === "");
  return {
    summary: `${count(matched.length)} leave ${field} blank.`,
    lines: [],
    rows: matched,
    filterLabel: `Blank ${field}`,
    highlightDay: null,
    suggestions: ["Find patterns in this file", "Show every sample"],
    action: null,
  };
}

function turnaroundReply(rows, report, q) {
  const slow = /\b(or more|at least|longer|slow|over|more than|7 days)\b/.test(q);
  if (slow) {
    const matched = rowsWhere(rows, (row) => {
      const days = turnaroundDays(row);
      return days != null && days >= 7;
    });
    return {
      summary: `${count(matched.length)} took 7 days or more from sampled to received.`,
      lines: report.medianTurnaround == null ? [] : [turnaroundLine(report)],
      rows: matched,
      filterLabel: "Turnaround of 7 days or more",
      highlightDay: null,
      suggestions: ["Show every sample"],
      action: null,
    };
  }
  return {
    summary:
      report.medianTurnaround == null
        ? "No row has both a sampled date and a received date."
        : `Median turnaround is ${report.medianTurnaround} ${report.medianTurnaround === 1 ? "day" : "days"}.`,
    lines: report.medianTurnaround == null ? [] : [turnaroundLine(report)],
    rows,
    filterLabel: null,
    highlightDay: null,
    suggestions: report.over7
      ? ["Show samples with a turnaround of 7 days or more"]
      : ["Find patterns in this file"],
    action: null,
  };
}

function sampledAfterReply(rows, report) {
  const matched = rowsWhere(rows, (row) => {
    const days = turnaroundDays(row);
    return days != null && days < 0;
  });
  return {
    summary: `${count(matched.length)} have Date Sampled after Date Received.`,
    lines:
      report.negativeTurnaround === 0
        ? ["Those dates agree on every row that has both."]
        : ["A sampled date after receipt is a label or entry error worth a look."],
    rows: matched,
    filterLabel: "Sampled after received",
    highlightDay: null,
    suggestions: ["Show every sample"],
    action: null,
  };
}

function duplicateReply(rows, report) {
  const dupes = new Set(report.duplicateIds.map((item) => item.id));
  const matched = rowsWhere(rows, (row) => dupes.has(String(row["Sample ID"] ?? "").trim()));
  return {
    summary: report.duplicateIds.length
      ? `${count(report.duplicateIds.length, "sample ID is repeated", "sample IDs are repeated")}.`
      : "Every sample ID is unique.",
    lines: report.duplicateIds.slice(0, 5).map((item) => `${item.id} appears ${item.count} times.`),
    rows: report.duplicateIds.length ? matched : rows,
    filterLabel: report.duplicateIds.length ? "Repeated sample IDs" : null,
    highlightDay: null,
    suggestions: ["Show every sample"],
    action: null,
  };
}

function classReply(rows, kind) {
  const matched = rowsWhere(rows, (row) => sampleClass(row) === kind);
  const label = kind === "small" ? "Small tubes" : "Large tubes";
  return {
    summary: `${count(matched.length)} are ${kind} tubes.`,
    lines: [
      kind === "small"
        ? "A small tube has a sample ID that starts with RN."
        : "A large tube is any sample ID that does not start with RN.",
    ],
    rows: matched,
    filterLabel: label,
    highlightDay: null,
    suggestions: ["Find patterns in this file", "Show every sample"],
    action: null,
  };
}

function keep(rows, summary, lines, suggestions = []) {
  return {
    summary,
    lines,
    rows,
    keep: true,
    filterLabel: null,
    highlightDay: null,
    suggestions,
    action: null,
  };
}

function isTurnaround(q) {
  return /turnaround|days between|how long|sampled to received|from sampled|lag between/.test(q);
}

function isSampledAfter(q) {
  return /sampled after|date sampled after|negative turnaround|after (they were |it was )?received/.test(
    q,
  );
}

function isMissing(q) {
  return /\b(missing|blank|empty|without|lacking|no|not have|don't have|do not have)\b/.test(q);
}

function missingField(q) {
  if (/\bserial\b|\bsn\b/.test(q)) return "Serial Number";
  if (/\breference lube\b|\bref lube\b|\blubes?\b|\blubricant\b/.test(q)) return "Reference Lube";
  if (/\bdate sampled\b|\bsampled date\b/.test(q)) return "Date Sampled";
  if (/\bdate received\b|\breceived date\b/.test(q)) return "Date Received";
  if (/\bsample ids?\b|\bbarcodes?\b/.test(q)) return "Sample ID";
  if (/\bcomponents?\b|\bsample points?\b/.test(q)) return "Component";
  if (/\bmachines?\b|\bequipment\b|\bequip id\b/.test(q)) return "Machine";
  return null;
}

function wantsMachineRank(q) {
  return /\b(which|busiest|top|most|ranking)\b/.test(q) && /\bmachines?\b|\bequipment\b/.test(q);
}

function wantsLubeRank(q) {
  return (
    /\b(which|top|most|common|ranking)\b/.test(q) &&
    /\blubes?\b|\blubricants?\b|\breference lube\b/.test(q)
  );
}

function wantsComponentRank(q) {
  return /\b(which|top|most|common|list)\b/.test(q) && /\bcomponents?\b|\bsample points?\b/.test(q);
}

function findDate(q) {
  let match = /\b(20\d{2})-(\d{1,2})-(\d{1,2})\b/.exec(q);
  if (match) return makeDate(match[1], match[2], match[3]);
  match = /\b(\d{1,2})\/(\d{1,2})\/(20\d{2})\b/.exec(q);
  if (match) return makeDate(match[3], match[1], match[2]);
  const monthFirst = new RegExp(
    `\\b(${MONTH_PATTERN})\\s+(\\d{1,2}),?\\s+(20\\d{2})\\b`,
  ).exec(q);
  if (monthFirst) return makeDate(monthFirst[3], MONTHS[monthFirst[1]], monthFirst[2]);
  const dayFirst = new RegExp(
    `\\b(\\d{1,2})\\s+(${MONTH_PATTERN})\\s+(20\\d{2})\\b`,
  ).exec(q);
  if (dayFirst) return makeDate(dayFirst[3], MONTHS[dayFirst[2]], dayFirst[1]);
  return null;
}

function makeDate(year, month, day) {
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
  return { iso: isoFromDate(date), date };
}

function matchNamed(q, names) {
  const sorted = [...names].sort((a, b) => b.length - a.length);
  const full = sorted.find((name) => q.includes(name.toLowerCase()));
  if (full) return full;
  const tokenHits = sorted.filter((name) =>
    name
      .toLowerCase()
      .split(/[^a-z0-9]+/)
      .filter((token) => token.length >= 4)
      .some((token) => new RegExp(`\\b${escapeRegExp(token)}\\b`).test(q)),
  );
  return tokenHits.length === 1 ? tokenHits[0] : null;
}

function matchMachine(q, names) {
  const named = matchNamed(q, names);
  if (named) return named;
  const found = names.filter((name) => {
    const code = name.split(/\s+/)[0];
    if (!code || code.length < 2) return false;
    return new RegExp(`\\b${escapeRegExp(code.toLowerCase())}\\b`).test(q);
  });
  return found.length === 1 ? found[0] : null;
}

function mix(rows, column) {
  const counts = new Map();
  for (const row of rows) {
    const value = String(row[column] ?? "").trim() || "(blank)";
    counts.set(value, (counts.get(value) ?? 0) + 1);
  }
  return [...counts.entries()]
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
}

function splitLine(report) {
  return `${count(report.large)} are large tubes and ${count(report.small)} are small tubes.`;
}

function serialLine(report) {
  const large =
    report.missingSerialLarge === 1 ? "1 large tube leaves" : `${report.missingSerialLarge} large tubes leave`;
  const small =
    report.missingSerialSmall === 1
      ? "1 small tube also has no serial, and that label does carry an SN."
      : `${report.missingSerialSmall} small tubes also have no serial, and those labels do carry an SN.`;
  return `${count(report.missingSerial)} have no serial number. ${large} serial blank, which matches the label guide. ${small}`;
}

function turnaroundLine(report) {
  return `Across ${count(report.turnaroundCount)} with both dates, ${count(report.over7)} took 7 days or more and ${count(report.negativeTurnaround)} have Date Sampled after Date Received.`;
}

function count(value, singular = "sample", plural = "samples") {
  const noun = value === 1 ? singular : plural;
  return `${value} ${noun}`;
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
