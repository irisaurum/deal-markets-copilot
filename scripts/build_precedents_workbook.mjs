import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const root = process.cwd();
const sourcePath = path.join(root, "data", "precedent_transactions.json");
const outputPath = path.join(root, "output", "precedent_transactions.xlsx");
const qaDir = path.join("/tmp", "deal-markets-copilot-xlsx-qa");
const rows = JSON.parse(await fs.readFile(sourcePath, "utf8"));

const wb = Workbook.create();
const dashboard = wb.worksheets.add("Deal Dashboard");
const precedents = wb.worksheets.add("Precedent Transactions");
const card = wb.worksheets.add("Deal Card");
const qa = wb.worksheets.add("Sources & QA");
for (const sheet of [dashboard, precedents, card, qa]) {
  sheet.showGridLines = false;
}

const navy = "#10243E";
const blue = "#1F4E78";
const teal = "#18A999";
const paleBlue = "#D9EAF7";
const paleGreen = "#E2F0D9";
const paleYellow = "#FFF2CC";
const paleRed = "#FCE4D6";
const light = "#F4F6F8";
const border = "#CCD5DF";
const white = "#FFFFFF";
const black = "#000000";
const green = "#008000";

function titleBand(sheet, range, title, subtitle) {
  sheet.getRange(range).merge();
  const anchor = range.split(":")[0];
  sheet.getRange(anchor).values = [[title]];
  sheet.getRange(range).format = { fill: navy, font: { color: white, bold: true, size: 18 }, verticalAlignment: "center" };
  sheet.getRange(range).format.rowHeight = 32;
  sheet.getRange("A2:H2").merge();
  sheet.getRange("A2").values = [[subtitle]];
  sheet.getRange("A2:H2").format = { fill: light, font: { color: "#52616F", italic: true, size: 9 }, verticalAlignment: "center" };
  sheet.getRange("A2:H2").format.rowHeight = 25;
}

function sectionHeader(sheet, range, text) {
  sheet.getRange(range).merge();
  const anchor = range.split(":")[0];
  sheet.getRange(anchor).values = [[text]];
  sheet.getRange(range).format = { fill: blue, font: { color: white, bold: true, size: 11 }, verticalAlignment: "center" };
  sheet.getRange(range).format.rowHeight = 22;
}

function formatHeaders(range) {
  range.format = { fill: navy, font: { color: white, bold: true, size: 9 }, wrapText: true, verticalAlignment: "center", borders: { preset: "outside", style: "thin", color: border } };
  range.format.rowHeight = 30;
}

// Deal Dashboard
titleBand(dashboard, "A1:H1", "DEAL MARKETS COPILOT — PRECEDENT TRANSACTIONS", `Screening-grade database | As of ${new Date().toISOString().slice(0, 10)} | Verify primary documents before use`);
sectionHeader(dashboard, "A4:H4", "DATABASE SNAPSHOT");
dashboard.getRange("A6:H6").values = [["Total deals", "M&A", "ECM", "DCM", "Disclosed value", "High score (≥7)", "Missing value", "QA status"]];
formatHeaders(dashboard.getRange("A6:H6"));
dashboard.getRange("A7:H7").formulas = [[
  "=COUNTA('Precedent Transactions'!$A$7:$A$506)",
  "=COUNTIF('Precedent Transactions'!$C$7:$C$506,\"M&A\")",
  "=COUNTIF('Precedent Transactions'!$C$7:$C$506,\"ECM\")",
  "=COUNTIF('Precedent Transactions'!$C$7:$C$506,\"DCM\")",
  "=SUM('Precedent Transactions'!$I$7:$I$506)",
  "=COUNTIF('Precedent Transactions'!$N$7:$N$506,\">=7\")",
  "=COUNTBLANK('Precedent Transactions'!$I$7:$I$506)-COUNTBLANK('Precedent Transactions'!$A$7:$A$506)",
  "='Sources & QA'!$F$29",
]];
dashboard.getRange("A7:H7").format = { fill: paleBlue, font: { bold: true, size: 14 }, verticalAlignment: "center", borders: { preset: "outside", style: "thin", color: border } };
dashboard.getRange("A7:H7").format.rowHeight = 32;
dashboard.getRange("E7").setNumberFormat("#,##0;[Red](#,##0);-");
dashboard.getRange("A6:H7").format.horizontalAlignment = "center";
sectionHeader(dashboard, "A10:H10", "LATEST TRANSACTIONS");
const latestHeaders = ["Date", "Type", "Status", "Target / Issuer", "Acquirer", "Value", "Currency", "Source"];
dashboard.getRange("A12:H12").values = [latestHeaders];
formatHeaders(dashboard.getRange("A12:H12"));
const latest = rows.slice(0, 10).map((r) => [toDate(r.announced_date), r.deal_type, r.status, r.target_or_issuer, r.acquirer_or_investor, r.transaction_value, r.currency, r.source_name]);
if (latest.length) dashboard.getRangeByIndexes(12, 0, latest.length, latestHeaders.length).values = latest;
dashboard.getRange(`A13:A${12 + Math.max(latest.length, 1)}`).setNumberFormat("dd-mmm-yyyy");
dashboard.getRange(`F13:F${12 + Math.max(latest.length, 1)}`).setNumberFormat("#,##0;[Red](#,##0);-");
dashboard.getRange(`A13:C${12 + Math.max(latest.length, 1)}`).format.horizontalAlignment = "center";
dashboard.getRange("A12:H22").format.borders = { insideHorizontal: { style: "thin", color: border } };
dashboard.freezePanes.freezeRows(4);
dashboard.getRange("A:H").format.columnWidth = 15;
dashboard.getRange("A:A").format.columnWidth = 18;
dashboard.getRange("D:E").format.columnWidth = 24;
dashboard.getRange("H:H").format.columnWidth = 22;

// Full precedent database
titleBand(precedents, "A1:T1", "PRECEDENT TRANSACTIONS DATABASE", "One row per source-backed transaction signal; blank economics mean not publicly disclosed, not zero");
precedents.getRange("A4:T4").merge();
precedents.getRange("A4").values = [["Legend: source/imported fields in green text · calculated dashboard outputs in black · screening limitations highlighted in notes"]];
precedents.getRange("A4:T4").format = { fill: paleYellow, font: { color: "#7F6000", size: 9 }, wrapText: true };
const headers = ["Deal ID", "Announced Date", "Type", "Status", "Target / Issuer", "Acquirer / Investor", "Sector", "Geography", "Transaction Value", "Currency", "Stake %", "Instrument", "Rationale / Use of Proceeds", "Score", "Evidence", "Coverage", "Source", "Source URL", "Headline", "Notes"];
precedents.getRange("A6:T6").values = [headers];
formatHeaders(precedents.getRange("A6:T6"));
const matrix = rows.map((r) => [r.deal_id, toDate(r.announced_date), r.deal_type, r.status, r.target_or_issuer, r.acquirer_or_investor, r.sector, r.geography, r.transaction_value, r.currency, r.stake_percent == null ? null : r.stake_percent / 100, r.instrument, r.rationale, r.score, r.evidence_label, (r.matched_coverage || []).join(", "), r.source_name, r.source_url, r.headline, r.notes]);
if (matrix.length) {
  precedents.getRangeByIndexes(6, 0, matrix.length, headers.length).values = matrix;
  const end = 6 + matrix.length;
  const table = precedents.tables.add(`A6:T${end}`, true, "PrecedentTransactionsTable");
  table.style = "TableStyleMedium2";
  precedents.getRange(`A7:T${end}`).format.font = { color: green, size: 9 };
  precedents.getRange(`B7:B${end}`).setNumberFormat("dd-mmm-yyyy");
  precedents.getRange(`I7:I${end}`).setNumberFormat("#,##0;[Red](#,##0);-");
  precedents.getRange(`K7:K${end}`).setNumberFormat("0.0%;[Red](0.0%);-");
  precedents.getRange(`M7:M${end}`).format.wrapText = true;
  precedents.getRange(`S7:T${end}`).format.wrapText = true;
  precedents.getRange(`N7:N${end}`).conditionalFormats.add("colorScale", { colors: ["#F8696B", "#FFEB84", "#63BE7B"], thresholds: ["min", "50%", "max"] });
}
precedents.freezePanes.freezeRows(6);
const widths = [20, 14, 10, 14, 24, 24, 16, 16, 18, 10, 11, 22, 34, 9, 13, 14, 20, 42, 52, 44];
widths.forEach((width, index) => precedents.getRangeByIndexes(0, index, Math.max(matrix.length + 6, 7), 1).format.columnWidth = width);

// Latest deal card
titleBand(card, "A1:H1", "DEAL CARD", "Latest highest-priority transaction from the database; blanks are explicitly labelled");
const deal = rows[0] || {};
sectionHeader(card, "A4:H4", `${deal.deal_type || "—"} | ${deal.status || "No transaction loaded"}`);
const cardRows = [
  ["Headline", deal.headline || "No deal available"],
  ["Announced date", toDate(deal.announced_date)],
  ["Target / Issuer", deal.target_or_issuer || "Not disclosed"],
  ["Acquirer / Investor", deal.acquirer_or_investor || "Not disclosed"],
  ["Transaction value", deal.transaction_value ?? null],
  ["Currency", deal.currency || "Not disclosed"],
  ["Stake", deal.stake_percent == null ? null : deal.stake_percent / 100],
  ["Instrument", deal.instrument || "Not disclosed"],
  ["Sector / geography", `${deal.sector || "Not classified"} / ${deal.geography || "Not disclosed"}`],
  ["Rationale / use of proceeds", deal.rationale || "Not disclosed"],
  ["Evidence / score", `${deal.evidence_label || "unverified"} / ${deal.score ?? "—"} out of 10`],
  ["Source", deal.source_name || "Not disclosed"],
  ["Source URL", deal.source_url || "Not disclosed"],
  ["Analyst note", "Screening only. Confirm parties, status, consideration and deal perimeter in primary documents."],
];
card.getRange("A6:B19").values = cardRows;
card.getRange("B18").values = [[deal.source_url ? "See Precedent Transactions → Source URL" : "Not disclosed"]];
card.getRange("A6:A19").format = { fill: light, font: { bold: true, color: navy }, borders: { insideHorizontal: { style: "thin", color: border } } };
card.getRange("B6:B19").format = { font: { color: green }, wrapText: true, borders: { insideHorizontal: { style: "thin", color: border } } };
card.getRange("B7").setNumberFormat("dd-mmm-yyyy");
card.getRange("B10").setNumberFormat("#,##0;[Red](#,##0);-");
card.getRange("B12").setNumberFormat("0.0%;[Red](0.0%);-");
card.getRange("A:A").format.columnWidth = 26;
card.getRange("B:B").format.columnWidth = 70;
card.getRange("A6:B19").format.rowHeight = 25;
card.getRange("B6:B19").format.verticalAlignment = "center";
card.freezePanes.freezeRows(4);

// Sources & QA
titleBand(qa, "A1:H1", "SOURCES & QA", "Visible audit checks for completeness, uniqueness and safe source links");
sectionHeader(qa, "A4:H4", "SOURCE REGISTER");
qa.getRange("A6:F6").values = [["Deal ID", "Date", "Source", "URL", "Evidence", "Headline"]];
formatHeaders(qa.getRange("A6:F6"));
const sourcePreview = rows.slice(0, 10);
const sourceRows = sourcePreview.map((r) => [r.deal_id, toDate(r.announced_date), r.source_name, "See Precedent Transactions → Source URL", r.evidence_label, r.headline]);
if (sourceRows.length) qa.getRangeByIndexes(6, 0, sourceRows.length, 6).values = sourceRows;
qa.getRange(`B7:B${6 + Math.max(sourceRows.length, 1)}`).setNumberFormat("dd-mmm-yyyy");
qa.getRange(`A7:F${6 + Math.max(sourceRows.length, 1)}`).format.font = { color: green, size: 9 };
qa.getRange(`A7:F${6 + Math.max(sourceRows.length, 1)}`).format.rowHeight = 28;
sectionHeader(qa, "A20:H20", "DATABASE CHECKS");
qa.getRange("A22:F22").values = [["Check", "Actual", "Expected", "Difference", "Tolerance", "Status"]];
formatHeaders(qa.getRange("A22:F22"));
qa.getRange("A23:A27").values = [["Duplicate deal IDs"], ["Missing source URLs"], ["Missing announced dates"], ["Unsafe / non-HTTP URLs"], ["Missing target / issuer"]];
const databaseEnd = 6 + Math.max(rows.length, 1);
qa.getRange("B23:B27").formulas = [[
  `=SUMPRODUCT(--(COUNTIF('Precedent Transactions'!$A$7:$A$${databaseEnd},'Precedent Transactions'!$A$7:$A$${databaseEnd})>1))/2`
], [
  `=COUNTBLANK('Precedent Transactions'!$R$7:$R$${databaseEnd})`
], [
  `=COUNTBLANK('Precedent Transactions'!$B$7:$B$${databaseEnd})`
], [
  `=SUMPRODUCT(--(LEFT('Precedent Transactions'!$R$7:$R$${databaseEnd},4)<>\"http\"),--('Precedent Transactions'!$A$7:$A$${databaseEnd}<>\"\"))`
], [
  `=COUNTIF('Precedent Transactions'!$E$7:$E$${databaseEnd},\"Not disclosed\")`
]];
qa.getRange("C23:C27").values = [[0], [0], [0], [0], [0]];
qa.getRange("D23:D27").formulas = [["=B23-C23"], ["=B24-C24"], ["=B25-C25"], ["=B26-C26"], ["=B27-C27"]];
qa.getRange("E23:E27").values = [[0], [0], [0], [0], [0]];
qa.getRange("F23:F27").formulas = [["=IF(ABS(D23)<=E23,\"OK\",\"REVIEW\")"], ["=IF(ABS(D24)<=E24,\"OK\",\"REVIEW\")"], ["=IF(ABS(D25)<=E25,\"OK\",\"REVIEW\")"], ["=IF(ABS(D26)<=E26,\"OK\",\"REVIEW\")"], ["=IF(ABS(D27)<=E27,\"OK\",\"REVIEW\")"]];
qa.getRange("A29:E29").merge();
qa.getRange("A29").values = [["Overall model status"]];
qa.getRange("F29").formulas = [["=IF(COUNTIF(F23:F27,\"REVIEW\")=0,\"OK\",\"REVIEW\")"]];
qa.getRange("A29:F29").format = { fill: navy, font: { color: white, bold: true }, borders: { preset: "outside", style: "thin", color: border } };
qa.getRange("F23:F29").conditionalFormats.add("containsText", { text: "OK", format: { fill: paleGreen, font: { color: "#006100", bold: true } } });
qa.getRange("F23:F29").conditionalFormats.add("containsText", { text: "REVIEW", format: { fill: paleRed, font: { color: "#9C0006", bold: true } } });
qa.getRange("A:F").format.columnWidth = 18;
qa.getRange("C:C").format.columnWidth = 24;
qa.getRange("D:D").format.columnWidth = 48;
qa.getRange("F:F").format.columnWidth = 55;
qa.getRange(`D7:F${6 + Math.max(sourceRows.length, 1)}`).format.wrapText = true;
qa.freezePanes.freezeRows(6);

await fs.mkdir(path.dirname(outputPath), { recursive: true });
const workbookFile = await SpreadsheetFile.exportXlsx(wb);
await workbookFile.save(outputPath);

const inspection = await wb.inspect({ kind: "sheet,table,formula", maxChars: 5000, tableMaxRows: 5, tableMaxCols: 8, options: { maxResults: 80 } });
console.log(inspection.ndjson || String(inspection));
await fs.mkdir(qaDir, { recursive: true });
for (const name of ["Deal Dashboard", "Precedent Transactions", "Deal Card", "Sources & QA"]) {
  const preview = await wb.render({ sheetName: name, autoCrop: "all", scale: 1, format: "png" });
  await fs.writeFile(path.join(qaDir, `${name.replaceAll(" ", "_")}.png`), new Uint8Array(await preview.arrayBuffer()));
}
console.log(`Workbook created: ${outputPath}`);
console.log(`QA renders: ${qaDir}`);
await fs.rm(`${outputPath}.inspect.ndjson`, { force: true });

function toDate(value) {
  return value ? new Date(`${value}T00:00:00Z`) : null;
}
