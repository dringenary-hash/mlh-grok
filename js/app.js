import { COLUMNS } from "./columns.js";
import { analyze, formatDate, sampleClass } from "./analyze.js";
import { interpret, starterQuestions } from "./chat.js";
import {
  inspectTable,
  readTable,
  rowsFromMapping,
  safeFileName,
  toCsv,
} from "./csv.js";
import { SAMPLE_WEEK_CSV, SAMPLE_WEEK_LABEL } from "./sample-week.js";

const PAGE_SIZE = 25;

const state = {
  allRows: [],
  questionRows: [],
  filterLabel: null,
  highlightDay: null,
  search: "",
  page: 0,
  sourceLabel: SAMPLE_WEEK_LABEL,
  sourceKind: "sample",
  pendingFileName: "",
  pendingMatrix: null,
};

const sourceLine = document.querySelector("#source-line");
const banner = document.querySelector("#banner");
const tableBody = document.querySelector("#table-body");
const filterLabel = document.querySelector("#filter-label");
const clearFilter = document.querySelector("#clear-filter");
const searchInput = document.querySelector("#search");
const pageLabel = document.querySelector("#page-label");
const pagePrev = document.querySelector("#page-prev");
const pageNext = document.querySelector("#page-next");
const dayChart = document.querySelector("#day-chart");
const log = document.querySelector("#log");
const suggestions = document.querySelector("#suggestions");
const askForm = document.querySelector("#ask-form");
const askInput = document.querySelector("#ask-input");
const fileInput = document.querySelector("#file-input");
const dropOverlay = document.querySelector("#drop-overlay");
const mapDialog = document.querySelector("#map-dialog");
const mapForm = document.querySelector("#map-form");
const mapNote = document.querySelector("#map-note");
const mapFields = document.querySelector("#map-fields");
const submitDialog = document.querySelector("#submit-dialog");
const submitForm = document.querySelector("#submit-form");
const submitSummary = document.querySelector("#submit-summary");
const submitError = document.querySelector("#submit-error");
const fileNameInput = document.querySelector("#file-name");
const downloadShown = document.querySelector("#download-shown");
const submitColumns = document.querySelector("#submit-columns");

document.querySelector("#import-btn").addEventListener("click", () => fileInput.click());
document.querySelector("#sample-btn").addEventListener("click", () => loadSampleWeek());
document.querySelector("#skip-btn").addEventListener("click", openSubmit);
clearFilter.addEventListener("click", () => ask("Show every sample"));
pagePrev.addEventListener("click", () => turnPage(-1));
pageNext.addEventListener("click", () => turnPage(1));
searchInput.addEventListener("input", () => {
  state.search = searchInput.value.trim();
  state.page = 0;
  renderTable();
});
fileInput.addEventListener("change", () => {
  const file = fileInput.files?.[0];
  fileInput.value = "";
  if (file) readFile(file);
});
askForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const question = askInput.value;
  askInput.value = "";
  ask(question);
});
mapForm.addEventListener("submit", (event) => {
  event.preventDefault();
  confirmMapping();
});
document.querySelector("#map-cancel").addEventListener("click", () => mapDialog.close());
submitForm.addEventListener("submit", (event) => {
  event.preventDefault();
  download(state.allRows);
});
document.querySelector("#submit-close").addEventListener("click", () => submitDialog.close());
downloadShown.addEventListener("click", () => download(visibleRows()));

let dragDepth = 0;

function hasFiles(transfer) {
  return Boolean(transfer && [...transfer.types].includes("Files"));
}

document.addEventListener("dragenter", (event) => {
  if (!hasFiles(event.dataTransfer)) return;
  event.preventDefault();
  dragDepth += 1;
  dropOverlay.hidden = false;
});
document.addEventListener("dragover", (event) => {
  if (!hasFiles(event.dataTransfer)) return;
  event.preventDefault();
});
document.addEventListener("dragleave", () => {
  dragDepth = Math.max(0, dragDepth - 1);
  if (dragDepth === 0) dropOverlay.hidden = true;
});
document.addEventListener("drop", (event) => {
  if (!hasFiles(event.dataTransfer)) return;
  event.preventDefault();
  dragDepth = 0;
  dropOverlay.hidden = true;
  const file = event.dataTransfer.files?.[0];
  if (file) readFile(file);
});

for (const field of COLUMNS) {
  const item = document.createElement("li");
  item.textContent = field;
  submitColumns.appendChild(item);
}

boot();

function loadSampleWeek() {
  const table = readTable(SAMPLE_WEEK_CSV);
  adopt(table.rows, {
    label: SAMPLE_WEEK_LABEL,
    kind: "sample",
    fileName: "output_example.csv",
  });
}

async function boot() {
  try {
    const response = await fetch("data/output_example.csv");
    if (response.ok) {
      const table = readTable(await response.text());
      if (table.ready && table.rows.length) {
        adopt(table.rows, {
          label: SAMPLE_WEEK_LABEL,
          kind: "sample",
          fileName: "output_example.csv",
        });
        return;
      }
    }
  } catch {
    // file:// and a failed fetch still have the embedded week.
  }
  loadSampleWeek();
}

function readFile(file) {
  const reader = new FileReader();
  reader.onload = () => {
    const text = String(reader.result ?? "");
    const table = readTable(text);
    if (table.error) {
      showBanner(table.error);
      return;
    }
    if (table.ready) {
      adopt(table.rows, {
        label: file.name,
        kind: "import",
        fileName: file.name,
        extras: table.extras,
      });
      return;
    }
    openMapping(file.name, table);
  };
  reader.readAsText(file);
}

function openMapping(fileName, table) {
  state.pendingFileName = fileName;
  state.pendingMatrix = table.matrix;
  mapFields.replaceChildren();
  const problems = [];
  if (table.missing.length) problems.push(`Still needed: ${table.missing.join(", ")}.`);
  if (table.conflicts.length) problems.push(`Used more than once: ${table.conflicts.join(", ")}.`);
  if (table.extras.length) problems.push(`Extra columns stay out of the export: ${table.extras.join(", ")}.`);
  mapNote.textContent = problems.join(" ") || "Confirm which header fills each prize column.";

  for (const field of COLUMNS) {
    const label = document.createElement("label");
    label.textContent = field;
    const select = document.createElement("select");
    select.name = field;
    const blank = document.createElement("option");
    blank.value = "";
    blank.textContent = "Not in this file";
    select.appendChild(blank);
    table.headers.forEach((header, index) => {
      if (!header) return;
      const option = document.createElement("option");
      option.value = String(index);
      option.textContent = header;
      if (table.mapping[field] === index) option.selected = true;
      select.appendChild(option);
    });
    label.appendChild(select);
    mapFields.appendChild(label);
  }
  mapDialog.showModal();
}

function confirmMapping() {
  const mapping = {};
  for (const field of COLUMNS) {
    const select = mapForm.elements.namedItem(field);
    mapping[field] = select.value === "" ? null : Number(select.value);
  }
  const used = Object.values(mapping).filter((index) => index != null);
  if (new Set(used).size !== used.length) {
    mapNote.textContent = "Each file column can fill only one prize column.";
    return;
  }
  const rows = rowsFromMapping(state.pendingMatrix, mapping);
  const inspected = inspectTable(state.pendingMatrix);
  mapDialog.close();
  adopt(rows, {
    label: state.pendingFileName,
    kind: "import",
    fileName: state.pendingFileName,
    extras: inspected.extras,
  });
}

function adopt(rows, source) {
  hideBanner();
  state.allRows = rows;
  state.questionRows = rows;
  state.filterLabel = null;
  state.highlightDay = null;
  state.search = "";
  state.page = 0;
  state.sourceLabel = source.label;
  state.sourceKind = source.kind;
  searchInput.value = "";
  log.replaceChildren();
  appendDesk(welcome(source));
  renderSuggestions(starterQuestions(rows));
  render();
}

function welcome(source) {
  const report = analyze(state.allRows);
  const span =
    report.receivedStart && report.receivedEnd
      ? `${report.receivedStart.label} – ${report.receivedEnd.label}`
      : "no received dates";
  const lines = [];
  if (source.kind === "sample") {
    lines.push(
      "This sample week was generated from the seven-column prize template. It is not customer data.",
    );
  } else {
    lines.push(`Loaded ${source.fileName}.`);
    if (source.extras?.length) {
      lines.push(`Left out of the sheet: ${source.extras.join(", ")}.`);
    }
  }
  lines.push(
    "Ask about machines, reference lubes, a received date, missing serial numbers, or turnaround. Skip to submission if you only need the CSV.",
  );
  return {
    summary: `${state.allRows.length} samples are on the sheet (${span}).`,
    lines,
  };
}

function ask(text) {
  const question = String(text ?? "").trim();
  if (!question) return;
  appendUser(question);
  const result = interpret(question, state.allRows);
  appendDesk(result);
  if (!result.keep && Array.isArray(result.rows)) {
    state.questionRows = result.rows;
    state.filterLabel = result.filterLabel;
    state.highlightDay = result.highlightDay;
    state.search = "";
    state.page = 0;
    searchInput.value = "";
    render();
  }
  if (result.suggestions?.length) renderSuggestions(result.suggestions);
  if (result.action === "submit") openSubmit();
}

function render() {
  const report = analyze(state.allRows);
  sourceLine.textContent =
    state.sourceKind === "sample"
      ? `${state.sourceLabel} · generated sample intake`
      : `Imported · ${state.sourceLabel}`;
  document.querySelector("#stat-count").textContent = String(report.count);
  document.querySelector("#stat-split").textContent = `${report.large} / ${report.small}`;
  document.querySelector("#stat-machines").textContent = String(report.namedMachines);
  document.querySelector("#stat-turnaround").textContent =
    report.medianTurnaround == null ? "–" : String(report.medianTurnaround);
  renderChart(report);
  renderTable();
}

function renderChart(report) {
  dayChart.replaceChildren();
  const max = Math.max(1, ...report.byDay.map((day) => day.count));
  for (const day of report.byDay) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "day";
    button.setAttribute("aria-pressed", day.iso !== "" && day.iso === state.highlightDay ? "true" : "false");
    button.setAttribute(
      "aria-label",
      day.iso
        ? `Show samples received on ${day.label}, ${day.count} samples`
        : `${day.count} samples have no date received`,
    );
    const count = document.createElement("span");
    count.className = "day-count";
    count.textContent = String(day.count);
    const bar = document.createElement("span");
    bar.className = "day-bar";
    bar.style.height = `${Math.max(12, Math.round((day.count / max) * 72))}px`;
    const label = document.createElement("span");
    label.className = "day-label";
    label.textContent = day.iso
      ? formatDate(new Date(`${day.iso}T00:00:00Z`)).replace(/^\w+\s/, "").replace(/\s\d{4}$/, "")
      : "No date";
    button.append(count, bar, label);
    if (day.iso) {
      button.addEventListener("click", () => ask(`Samples received on ${day.label}`));
    }
    dayChart.appendChild(button);
  }
}

function visibleRows() {
  const needle = state.search.toLowerCase();
  if (!needle) return state.questionRows;
  return state.questionRows.filter((row) =>
    Object.values(row).some((value) => String(value).toLowerCase().includes(needle)),
  );
}

function renderTable() {
  const rows = visibleRows();
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  if (state.page > pages - 1) state.page = pages - 1;
  const start = state.page * PAGE_SIZE;
  const slice = rows.slice(start, start + PAGE_SIZE);
  tableBody.replaceChildren();

  if (!slice.length) {
    const row = document.createElement("tr");
    row.className = "empty";
    const cell = document.createElement("td");
    cell.colSpan = 8;
    cell.textContent = state.allRows.length
      ? "No samples match this question."
      : "Import a CSV or load the sample week.";
    row.appendChild(cell);
    tableBody.appendChild(row);
  } else {
    for (const record of slice) {
      const row = document.createElement("tr");
      const tube = document.createElement("td");
      tube.className = "tube";
      const kind = sampleClass(record);
      tube.textContent = kind === "unknown" ? "–" : kind;
      row.appendChild(tube);
      for (const field of COLUMNS) {
        const cell = document.createElement("td");
        const value = record[field];
        if (!value) {
          cell.className = "blank";
          cell.textContent = "blank";
        } else {
          cell.textContent = value;
        }
        row.appendChild(cell);
      }
      tableBody.appendChild(row);
    }
  }

  const shownStart = rows.length ? start + 1 : 0;
  const shownEnd = start + slice.length;
  const qualifier = state.filterLabel ? ` · ${state.filterLabel}` : "";
  filterLabel.textContent = `Showing ${shownStart}–${shownEnd} of ${rows.length}${qualifier}`;
  pageLabel.textContent = `Page ${state.page + 1} of ${pages}`;
  pagePrev.disabled = state.page === 0;
  pageNext.disabled = state.page >= pages - 1;
  const narrowed = state.filterLabel || state.search;
  clearFilter.hidden = !narrowed;
}

function turnPage(delta) {
  state.page += delta;
  renderTable();
}

function renderSuggestions(questions) {
  suggestions.replaceChildren();
  for (const question of questions) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = question;
    button.addEventListener("click", () => ask(question));
    suggestions.appendChild(button);
  }
}

function appendUser(text) {
  const article = document.createElement("article");
  article.className = "message user";
  const paragraph = document.createElement("p");
  paragraph.textContent = text;
  article.appendChild(paragraph);
  log.appendChild(article);
  log.scrollTop = log.scrollHeight;
}

function appendDesk(result) {
  const article = document.createElement("article");
  article.className = "message desk";
  const heading = document.createElement("h3");
  heading.textContent = result.summary;
  article.appendChild(heading);
  if (result.lines?.length) {
    const list = document.createElement("ul");
    for (const line of result.lines) {
      const item = document.createElement("li");
      item.textContent = line;
      list.appendChild(item);
    }
    article.appendChild(list);
  }
  log.appendChild(article);
  log.scrollTop = log.scrollHeight;
}

function openSubmit() {
  const report = analyze(state.allRows);
  const start = report.receivedStart?.iso ?? "intake";
  fileNameInput.value = `mrg-intake-${start}.csv`;
  submitError.textContent = "";
  const shown = visibleRows().length;
  submitSummary.textContent = `${report.count} samples in the full file. The sheet is showing ${shown}.`;
  downloadShown.hidden = shown === report.count;
  downloadShown.textContent = `Download the ${shown} rows in the table`;
  submitDialog.showModal();
  fileNameInput.focus();
  fileNameInput.select();
}

function download(rows) {
  const name = safeFileName(fileNameInput.value);
  if (!name) {
    submitError.textContent = "Enter a file name.";
    return;
  }
  if (!rows.length) {
    submitError.textContent = "There are no rows to download.";
    return;
  }
  const blob = new Blob([toCsv(rows)], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  submitError.textContent = "";
  submitSummary.textContent = `Download started for ${name}. ${rows.length} data rows, seven columns.`;
}

function showBanner(message) {
  banner.hidden = false;
  banner.textContent = message;
}

function hideBanner() {
  banner.hidden = true;
  banner.textContent = "";
}
