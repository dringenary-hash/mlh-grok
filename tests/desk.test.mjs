import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { analyze } from "../js/analyze.js";
import { interpret } from "../js/chat.js";
import { COLUMNS } from "../js/columns.js";
import { readTable, safeFileName, toCsv } from "../js/csv.js";
import { SAMPLE_WEEK_CSV } from "../js/sample-week.js";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const examplePath = join(root, "data", "output_example.csv");

function loadExample() {
  return readTable(readFileSync(examplePath, "utf8")).rows;
}

function row(values) {
  return {
    "Sample ID": values.id,
    "Date Sampled": values.sampled,
    "Date Received": values.received,
    Machine: values.machine,
    Component: values.component,
    "Serial Number": values.serial,
    "Reference Lube": values.lube,
  };
}

const fixture = [
  row({
    id: "10000001",
    sampled: "2026-11-01",
    received: "2026-11-02",
    machine: "C-101 Conveyor Gearbox",
    component: "DE Bearing",
    serial: "",
    lube: "Mobilgrease XHP 222",
  }),
  row({
    id: "10000002",
    sampled: "2026-11-02",
    received: "2026-11-02",
    machine: "P-201 Boiler Feed Pump",
    component: "NDE Bearing",
    serial: "",
    lube: "Shell Gadus S2 V100 2",
  }),
  row({
    id: "10000001",
    sampled: "2026-10-20",
    received: "2026-11-02",
    machine: "C-101 Conveyor Gearbox",
    component: "Input Shaft",
    serial: "",
    lube: "Mobilgrease XHP 222",
  }),
  row({
    id: "RN-3000 GS",
    sampled: "2026-11-04",
    received: "2026-11-04",
    machine: "",
    component: "",
    serial: "SN800000",
    lube: "",
  }),
  row({
    id: "RN-3001 NGS",
    sampled: "2026-11-04",
    received: "2026-11-04",
    machine: "",
    component: "",
    serial: "",
    lube: "",
  }),
  row({
    id: "10000004",
    sampled: "2026-11-08",
    received: "2026-11-05",
    machine: "F-301 ID Fan",
    component: "DE Bearing",
    serial: "",
    lube: "",
  }),
];

test("sample week matches the prize template and the fixed intake story", () => {
  const csv = readFileSync(examplePath, "utf8");
  assert.equal(SAMPLE_WEEK_CSV, csv);
  const table = readTable(csv);
  assert.equal(table.ready, true);
  assert.deepEqual(Object.keys(table.rows[0]), COLUMNS);
  assert.equal(csv.split("\n")[0], COLUMNS.join(","));
  assert.equal(table.rows.length, 624);

  const report = analyze(table.rows);
  assert.equal(report.large, 406);
  assert.equal(report.small, 218);
  assert.equal(report.busiestDay.iso, "2026-11-02");
  assert.equal(report.busiestDay.count, 150);
  assert.equal(report.busiestDay.label, "Mon 2 Nov 2026");
  assert.equal(report.topMachines[0].name, "C-101 Conveyor Gearbox");
  assert.equal(report.topMachines[0].count, 72);
  assert.equal(report.topLubes[0].name, "Mobilgrease XHP 222");
  assert.equal(report.topLubes[0].count, 140);
  assert.equal(report.missingSerialSmall, 12);
  assert.equal(report.missingSerialLarge, 406);
  assert.equal(report.negativeTurnaround, 6);
  assert.equal(report.over7, 30);
  assert.equal(report.duplicateIds.length, 3);
  assert.equal(report.blankMachine, 223);
  assert.equal(report.blankLube, 238);

  const c101 = table.rows.filter((record) => record.Machine === "C-101 Conveyor Gearbox");
  assert.equal(c101.length, 72);
  assert.ok(c101.every((record) => record["Reference Lube"] === "Mobilgrease XHP 222"));
  assert.ok(c101.every((record) => record["Serial Number"] === ""));

  const exported = toCsv(table.rows);
  assert.equal(exported.includes("blank"), false);
  assert.equal(readTable(exported).rows.length, 624);
});

test("prize header names map onto the seven columns", () => {
  const text = [
    "Barcode,Date,Today's Date,Equip ID,Sample Point,SN,Ref Lube,Customer",
    '100,"Fan, ID note",2026-11-03,C-101,DE Bearing,,Mobilgrease XHP 222,York',
    "",
  ].join("\n");
  const table = readTable(text);
  assert.equal(table.ready, true);
  assert.deepEqual(table.extras, ["Customer"]);
  assert.equal(table.rows.length, 1);
  assert.equal(table.rows[0]["Sample ID"], "100");
  assert.equal(table.rows[0]["Date Sampled"], "Fan, ID note");
  assert.equal(table.rows[0]["Date Received"], "2026-11-03");
  assert.equal(table.rows[0].Machine, "C-101");
  assert.equal(table.rows[0]["Serial Number"], "");
  assert.equal(table.rows[0]["Reference Lube"], "Mobilgrease XHP 222");
  assert.equal(safeFileName(" Weekly Intake "), "Weekly-Intake.csv");
  assert.equal(safeFileName("mrg-intake-2026-11-02.csv"), "mrg-intake-2026-11-02.csv");
  assert.equal(safeFileName("../secret"), "secret.csv");
});

test("questions pull the rows a tech asked for", () => {
  const patterns = interpret("Find patterns in this file", fixture);
  assert.match(patterns.summary, /Patterns/);
  assert.match(patterns.lines.join(" "), /C-101 Conveyor Gearbox/);
  assert.equal(patterns.rows.length, fixture.length);

  const machines = interpret("Which machines sent the most samples?", fixture);
  assert.match(machines.summary, /C-101 Conveyor Gearbox/);
  assert.match(machines.lines[0], /72|2\.|C-101/);

  const serials = interpret("How many samples are missing a serial number?", fixture);
  assert.equal(serials.rows.length, 5);
  assert.match(serials.lines[0], /1 small tube/);

  const smallSerial = interpret("Show small tubes missing a serial number", fixture);
  assert.equal(smallSerial.rows.length, 1);
  assert.equal(smallSerial.rows[0]["Sample ID"], "RN-3001 NGS");

  const turnaround = interpret("What is the turnaround from sampled to received?", fixture);
  assert.match(turnaround.summary, /Median turnaround/);
  assert.equal(turnaround.filterLabel, null);

  const slow = interpret("Show samples with a turnaround of 7 days or more", fixture);
  assert.equal(slow.rows.length, 1);
  assert.equal(slow.rows[0]["Sample ID"], "10000001");

  const received = interpret("Samples received on Mon 2 Nov 2026", fixture);
  assert.equal(received.rows.length, 3);
  assert.equal(received.highlightDay, "2026-11-02");

  const backwards = interpret("Which rows were sampled after they were received?", fixture);
  assert.equal(backwards.rows.length, 1);
  assert.equal(backwards.rows[0]["Sample ID"], "10000004");

  const dupes = interpret("Are any sample IDs duplicated?", fixture);
  assert.equal(dupes.rows.length, 2);
  assert.match(dupes.lines[0], /10000001/);

  const lube = interpret("Show samples with Mobilgrease XHP 222", fixture);
  assert.equal(lube.rows.length, 2);

  const oneMachine = interpret("Show samples for C-101", fixture);
  assert.equal(oneMachine.rows.length, 2);

  const help = interpret("What is the weather?", fixture);
  assert.equal(help.keep, true);
  assert.match(help.summary, /seven columns/);

  const submit = interpret("Skip to submission", fixture);
  assert.equal(submit.action, "submit");
  assert.equal(submit.keep, true);
});

test("the sample week answers the six desk questions", () => {
  const rows = loadExample();
  const patterns = interpret("Find patterns in this file", rows);
  const text = patterns.lines.join(" ");
  assert.match(text, /C-101 Conveyor Gearbox/);
  assert.match(text, /Mobilgrease XHP 222/);
  assert.match(text, /12 small tubes/);
  assert.match(text, /Mon 2 Nov 2026/);

  assert.equal(
    interpret("Samples received on Mon 2 Nov 2026", rows).rows.length,
    150,
  );
  assert.equal(
    interpret("Show small tubes missing a serial number", rows).rows.length,
    12,
  );
  assert.equal(
    interpret("Show samples with a turnaround of 7 days or more", rows).rows.length,
    30,
  );
  assert.equal(interpret("Show samples for C-101 Conveyor Gearbox", rows).rows.length, 72);
  const ranked = interpret("Which reference lubes show up most?", rows);
  assert.match(ranked.summary, /Mobilgrease XHP 222/);
});
