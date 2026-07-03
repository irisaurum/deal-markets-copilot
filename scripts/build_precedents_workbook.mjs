import fs from "node:fs/promises";
import path from "node:path";
import { createHash } from "node:crypto";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const root = process.cwd();
const datasetRaw = await fs.readFile(path.join(root, "data", "precedent_transactions.json"));
const rows = JSON.parse(datasetRaw.toString("utf8"));
const outputPath = path.join(root, "output", "precedent_transactions.xlsx");
const qaDir = path.join("/tmp", "deal-markets-copilot-xlsx-qa");
const datasetSha256 = createHash("sha256").update(datasetRaw).digest("hex");
const buildId = datasetSha256.slice(0,12);
const wb = Workbook.create();
const summary = wb.worksheets.add("Summary");
const deals = wb.worksheets.add("Deals");
const financials = wb.worksheets.add("Financials");
const multiples = wb.worksheets.add("Multiples");
const qa = wb.worksheets.add("Sources & QA");
for (const sheet of [summary, deals, financials, multiples, qa]) sheet.showGridLines = false;

const C = {navy:"#10243E",blue:"#1F4E78",paleBlue:"#D9EAF7",green:"#008000",paleGreen:"#E2F0D9",yellow:"#FFF2CC",red:"#9C0006",paleRed:"#FCE4D6",light:"#F4F6F8",border:"#CCD5DF",white:"#FFFFFF",muted:"#52616F"};
const toDate = value => /^\d{4}-\d{2}-\d{2}/.test(String(value || "")) ? new Date(`${String(value).slice(0,10)}T00:00:00Z`) : null;
const safe = value => value === undefined ? null : value;
const lastRow = (count, start=7) => start + Math.max(count, 1) - 1;

function titleBand(sheet, endCol, title, subtitle) {
  sheet.getRange(`A1:${endCol}1`).merge(); sheet.getRange("A1").values=[[title]];
  sheet.getRange(`A1:${endCol}1`).format={fill:C.navy,font:{color:C.white,bold:true,size:18},verticalAlignment:"center",rowHeight:34};
  sheet.getRange(`A2:${endCol}2`).merge(); sheet.getRange("A2").values=[[subtitle]];
  sheet.getRange(`A2:${endCol}2`).format={fill:C.light,font:{color:C.muted,italic:true,size:9},verticalAlignment:"center",rowHeight:26};
}
function section(sheet, range, text) { sheet.getRange(range).merge(); sheet.getRange(range.split(":")[0]).values=[[text]]; sheet.getRange(range).format={fill:C.blue,font:{color:C.white,bold:true,size:11},rowHeight:23,verticalAlignment:"center"}; }
function headers(range) { range.format={fill:C.navy,font:{color:C.white,bold:true,size:9},wrapText:true,rowHeight:34,verticalAlignment:"center",borders:{preset:"outside",style:"thin",color:C.border}}; }
function styleTable(sheet, address, name) { const table=sheet.tables.add(address,true,name); table.style="TableStyleMedium2"; return table; }
function setWidths(sheet, widths, rowsCount) { widths.forEach((width,index)=>sheet.getRangeByIndexes(0,index,rowsCount,1).format.columnWidth=width); }

// SUMMARY
titleBand(summary,"J","DEAL MARKETS COPILOT — SUMMARY",`Quality-controlled transaction monitor | As of ${new Date().toISOString().slice(0,10)} | Build ${buildId} | N/M means insufficient or non-comparable disclosure`);
section(summary,"A4:J4","DATABASE SNAPSHOT");
summary.getRange("A6:J6").values=[["Total records","M&A","ECM","DCM","Approved","Review","Financials","EV/Revenue coverage","EV/EBITDA coverage","Model status"]]; headers(summary.getRange("A6:J6"));
summary.getRange("A7:J7").formulas=[["=COUNTA('Deals'!$A$7:$A$506)","=COUNTIF('Deals'!$C$7:$C$506,\"M&A\")","=COUNTIF('Deals'!$C$7:$C$506,\"ECM\")","=COUNTIF('Deals'!$C$7:$C$506,\"DCM\")","=COUNTIF('Deals'!$AN$7:$AN$506,\"approved\")","=COUNTIF('Deals'!$AN$7:$AN$506,\"review\")","=COUNTA('Financials'!$A$7:$A$506)","=COUNTIFS('Multiples'!$M$7:$M$506,\"YES\",'Multiples'!$K$7:$K$506,\">0\")","=COUNTIFS('Multiples'!$M$7:$M$506,\"YES\",'Multiples'!$L$7:$L$506,\">0\")","='Sources & QA'!$P$19"]];
summary.getRange("A7:J7").format={fill:C.paleBlue,font:{bold:true,size:13},horizontalAlignment:"center",rowHeight:32,borders:{preset:"outside",style:"thin",color:C.border}};
section(summary,"A10:J10","PRECEDENT VALUATION — APPROVED M&A ONLY");
summary.getRange("A12:D12").values=[["Median EV / Revenue","Median EV / EBITDA","EV / Revenue observations","EV / EBITDA observations"]]; headers(summary.getRange("A12:D12"));
summary.getRange("A13:D13").formulas=[["=IF(COUNTIFS('Multiples'!$M$7:$M$506,\"YES\",'Multiples'!$K$7:$K$506,\">0\")<3,\"N/M\",IFERROR(MEDIAN(FILTER('Multiples'!$K$7:$K$506,('Multiples'!$M$7:$M$506=\"YES\")*('Multiples'!$K$7:$K$506>0))),\"N/M\"))","=IF(COUNTIFS('Multiples'!$M$7:$M$506,\"YES\",'Multiples'!$L$7:$L$506,\">0\")<3,\"N/M\",IFERROR(MEDIAN(FILTER('Multiples'!$L$7:$L$506,('Multiples'!$M$7:$M$506=\"YES\")*('Multiples'!$L$7:$L$506>0))),\"N/M\"))","=COUNTIFS('Multiples'!$M$7:$M$506,\"YES\",'Multiples'!$K$7:$K$506,\">0\")","=COUNTIFS('Multiples'!$M$7:$M$506,\"YES\",'Multiples'!$L$7:$L$506,\">0\")"]];
summary.getRange("A13:D13").format={fill:C.paleGreen,font:{bold:true,size:14},horizontalAlignment:"center",rowHeight:32}; summary.getRange("A13:B13").setNumberFormat("0.0x");
section(summary,"A16:J16","LATEST KEY TRANSACTIONS");
summary.getRange("A18:J18").values=[["Date","Type","Status","Target / Issuer","Buyer / Investor","Value","Currency","Quality","Sources","Headline"]]; headers(summary.getRange("A18:J18"));
const latest=rows.filter(r=>r.record_kind==="deal"&&r.quality_status!=="rejected").slice(0,10).map(r=>[toDate(r.announced_date),r.deal_type,r.status,r.target_or_issuer,r.acquirer_or_investor,r.transaction_value,r.currency,r.quality_status,r.source_count,r.headline]);
if(latest.length) summary.getRangeByIndexes(18,0,latest.length,10).values=latest;
summary.getRange(`A19:A${18+Math.max(latest.length,1)}`).setNumberFormat("dd-mmm-yyyy"); summary.getRange(`F19:F${18+Math.max(latest.length,1)}`).setNumberFormat("#,##0;[Red](#,##0);-");
summary.getRange(`A19:J${18+Math.max(latest.length,1)}`).format={wrapText:true,rowHeight:30,verticalAlignment:"center"};
setWidths(summary,[14,10,14,24,24,18,10,12,10,48],30); summary.freezePanes.freezeRows(4);

// DEALS
titleBand(deals,"AT","DEALS","Normalized transaction database with separate M&A, DCM and ECM fields; sourced values are green and calculated outputs are black");
deals.getRange("A4:AT4").merge(); deals.getRange("A4").values=[["Use filters in row 6. Blank values mean not disclosed; they are never treated as zero."]]; deals.getRange("A4:AT4").format={fill:C.yellow,font:{color:"#7F6000",size:9}};
const dealHeaders=["Deal ID","Announced Date","Type","Record Kind","Status","Target / Issuer","Buyer / Investor","Seller","Sector","Geography","Transaction Value","Enterprise Value","Currency","Stake %","Payment Form","Advisors","Instrument","Security Code","ISIN","Coupon %","Coupon Type","Yield %","Maturity","Tenor","Issue Price","Price / Share","Discount %","Bookrunners","Free Float %","Rationale","Revenue LTM","EBITDA LTM","Financials As Of","Financials Currency","EV / Revenue","EV / EBITDA","Financial Source","Metric Basis","Multiple Notes","Quality","Quality Score","Evidence","Source Count","Primary Source","Primary URL","Headline"];
deals.getRange("A6:AT6").values=[dealHeaders]; headers(deals.getRange("A6:AT6"));
const dealMatrix=rows.map(r=>[r.deal_id,toDate(r.announced_date),r.deal_type,r.record_kind,r.status,r.target_or_issuer,r.acquirer_or_investor,r.seller,r.sector,r.geography,r.transaction_value,r.enterprise_value,r.currency,r.stake_percent==null?null:r.stake_percent/100,r.payment_form,r.advisors,r.instrument,r.security_code,r.isin,r.coupon_rate==null?null:r.coupon_rate/100,r.coupon_type,r.yield_rate==null?null:r.yield_rate/100,toDate(r.maturity_date),r.tenor,r.issue_price,r.price_per_share,r.discount_percent==null?null:r.discount_percent/100,r.bookrunners,r.free_float_percent==null?null:r.free_float_percent/100,r.rationale,r.revenue_ltm,r.ebitda_ltm,toDate(r.financials_as_of),r.financials_currency,r.ev_revenue,r.ev_ebitda,r.financials_source_name,r.financials_metric_basis,r.multiple_notes,r.quality_status,r.quality_score,r.evidence_label,r.source_count,r.source_name,r.source_url,r.headline]);
if(dealMatrix.length){const end=lastRow(dealMatrix.length); deals.getRangeByIndexes(6,0,dealMatrix.length,dealHeaders.length).values=dealMatrix; styleTable(deals,`A6:AT${end}`,"DealsTable"); deals.getRange(`A7:AT${end}`).format.font={color:C.green,size:9}; deals.getRange(`AI7:AJ${end}`).format.font={color:"#000000",size:9}; deals.getRange(`B7:B${end}`).setNumberFormat("dd-mmm-yyyy"); deals.getRange(`K7:L${end}`).setNumberFormat("#,##0;[Red](#,##0);-"); deals.getRange(`N7:N${end}`).setNumberFormat("0.0%;[Red](0.0%);-"); deals.getRange(`T7:T${end}`).setNumberFormat("0.0%;[Red](0.0%);-"); deals.getRange(`V7:V${end}`).setNumberFormat("0.0%;[Red](0.0%);-"); deals.getRange(`W7:W${end}`).setNumberFormat("dd-mmm-yyyy"); deals.getRange(`AA7:AA${end}`).setNumberFormat("0.0%;[Red](0.0%);-"); deals.getRange(`AC7:AC${end}`).setNumberFormat("0.0%;[Red](0.0%);-"); deals.getRange(`AE7:AF${end}`).setNumberFormat("#,##0;[Red](#,##0);-"); deals.getRange(`AG7:AG${end}`).setNumberFormat("dd-mmm-yyyy"); deals.getRange(`AI7:AJ${end}`).setNumberFormat("0.0x");}
setWidths(deals,[20,14,9,15,13,24,24,20,15,15,18,18,10,10,16,28,20,22,16,11,13,11,14,14,13,13,11,25,11,34,18,18,16,15,13,13,28,38,42,12,12,12,11,24,42,52],Math.max(rows.length+7,8)); deals.freezePanes.freezeRows(6);

// FINANCIALS
const finRows=rows.filter(r=>r.revenue_ltm||r.ebitda_ltm||r.financials_source_url);
titleBand(financials,"N","FINANCIALS","One row per transaction financial dataset; dates distinguish the metric period from public availability");
const finHeaders=["Deal ID","Target","Deal Date","Financials As Of","Available At","Currency","Revenue LTM","Operating Income","Depreciation","Amortization","EBITDA LTM","Metric Basis","Source","Source URL"];
financials.getRange("A6:N6").values=[finHeaders]; headers(financials.getRange("A6:N6"));
const finMatrix=finRows.map(r=>[r.deal_id,r.target_or_issuer,toDate(r.announced_date),toDate(r.financials_as_of),toDate(r.financials_available_at),r.financials_currency,r.revenue_ltm,r.operating_income,r.depreciation,r.amortization,r.ebitda_ltm,r.financials_metric_basis,r.financials_source_name,r.financials_source_url]);
if(finMatrix.length){const end=lastRow(finMatrix.length);financials.getRangeByIndexes(6,0,finMatrix.length,finHeaders.length).values=finMatrix;styleTable(financials,`A6:N${end}`,"FinancialsTable");financials.getRange(`A7:N${end}`).format.font={color:C.green,size:9};financials.getRange(`C7:E${end}`).setNumberFormat("dd-mmm-yyyy");financials.getRange(`G7:K${end}`).setNumberFormat("#,##0;[Red](#,##0);-");financials.getRange(`L7:N${end}`).format={wrapText:true,rowHeight:48,verticalAlignment:"top"};}
setWidths(financials,[24,24,14,16,16,11,18,18,16,16,18,52,30,48],Math.max(finRows.length+7,8)); financials.freezePanes.freezeRows(6);

// MULTIPLES
const maRows=rows.filter(r=>r.deal_type==="M&A");
titleBand(multiples,"O","MULTIPLES","Only approved M&A with contemporaneously available financials enters the model median");
const multHeaders=["Deal ID","Date","Target","Enterprise Value","EV Currency","Revenue LTM","EBITDA LTM","Financials Currency","Quality","Available at announcement","EV / Revenue","EV / EBITDA","Model Eligible","Financial Source","Notes"];
multiples.getRange("A6:O6").values=[multHeaders]; headers(multiples.getRange("A6:O6"));
const multMatrix=maRows.map(r=>[r.deal_id,toDate(r.announced_date),r.target_or_issuer,r.enterprise_value,r.currency,r.revenue_ltm,r.ebitda_ltm,r.financials_currency,r.quality_status,(r.financials_available_at&&r.announced_date&&String(r.financials_available_at).slice(0,10)<=String(r.announced_date).slice(0,10))?"YES":"NO",null,null,null,r.financials_source_name,r.multiple_notes]);
if(multMatrix.length){const end=lastRow(multMatrix.length);multiples.getRangeByIndexes(6,0,multMatrix.length,multHeaders.length).values=multMatrix;for(let row=7;row<=end;row++){multiples.getRange(`K${row}`).formulas=[[`=IFERROR(IF(AND($D${row}>0,$F${row}>0,$E${row}=$H${row}),$D${row}/$F${row},\"\"),\"\")`]];multiples.getRange(`L${row}`).formulas=[[`=IFERROR(IF(AND($D${row}>0,$G${row}>0,$E${row}=$H${row}),$D${row}/$G${row},\"\"),\"\")`]];multiples.getRange(`M${row}`).formulas=[[`=IF(AND($I${row}=\"approved\",$J${row}=\"YES\",OR($K${row}>0,$L${row}>0)),\"YES\",\"NO\")`]];}styleTable(multiples,`A6:O${end}`,"MultiplesTable");multiples.getRange(`A7:J${end}`).format.font={color:C.green,size:9};multiples.getRange(`K7:M${end}`).format.font={color:"#000000",size:9};multiples.getRange(`B7:B${end}`).setNumberFormat("dd-mmm-yyyy");multiples.getRange(`D7:D${end}`).setNumberFormat("#,##0;[Red](#,##0);-");multiples.getRange(`F7:G${end}`).setNumberFormat("#,##0;[Red](#,##0);-");multiples.getRange(`K7:L${end}`).setNumberFormat("0.0x");multiples.getRange(`M7:M${end}`).conditionalFormats.add("containsText",{text:"YES",format:{fill:C.paleGreen,font:{color:"#006100",bold:true}}});multiples.getRange(`M7:M${end}`).conditionalFormats.add("containsText",{text:"NO",format:{fill:C.paleRed,font:{color:C.red,bold:true}}});}
setWidths(multiples,[28,14,24,20,12,18,18,14,12,20,14,14,13,32,55],Math.max(maRows.length+7,8)); multiples.freezePanes.freezeRows(6);

// SOURCES & QA
const sourceRows=rows.flatMap(r=>(r.sources||[]).map(source=>[r.deal_id,toDate(r.announced_date),r.target_or_issuer,source.name,source.source_type,source.evidence_label,source.url,toDate(source.published_at?.slice?.(0,10)),r.headline]));
titleBand(qa,"P","SOURCES & QA","Source register plus visible model checks; every calculation can be traced to a public URL");
section(qa,"A4:I4","SOURCE REGISTER"); qa.getRange("A6:I6").values=[["Deal ID","Deal Date","Target / Issuer","Source","Type","Evidence","URL","Published","Headline"]]; headers(qa.getRange("A6:I6"));
if(sourceRows.length){const end=lastRow(sourceRows.length);qa.getRangeByIndexes(6,0,sourceRows.length,9).values=sourceRows;styleTable(qa,`A6:I${end}`,"SourcesTable");qa.getRange(`A7:I${end}`).format.font={color:C.green,size:9};qa.getRange(`B7:B${end}`).setNumberFormat("dd-mmm-yyyy");qa.getRange(`H7:H${end}`).setNumberFormat("dd-mmm-yyyy");}
section(qa,"K4:P4","MODEL CHECKS"); qa.getRange("K6:P6").values=[["Check","Actual","Expected","Difference","Tolerance","Status"]]; headers(qa.getRange("K6:P6"));
qa.getRange("K7:K17").values=[["Duplicate deal IDs"],["Missing primary URLs"],["Missing announced dates"],["Unsafe URLs"],["Eligible multiples without EV"],["Eligible multiples with currency mismatch"],["Financials without source"],["Approved non-deal records"],["Stake populated outside M&A"],["Buyer populated for DCM"],["Eligible multiple observations"]];
qa.getRange("L7:L17").formulas=[["=SUMPRODUCT(--(COUNTIF('Deals'!$A$7:$A$506,'Deals'!$A$7:$A$506)>1))/2"],["=COUNTIFS('Deals'!$A$7:$A$506,\"<>\",'Deals'!$AS$7:$AS$506,\"\")"],["=COUNTIFS('Deals'!$A$7:$A$506,\"<>\",'Deals'!$B$7:$B$506,\"\")"],["=SUMPRODUCT(--(LEFT('Deals'!$AS$7:$AS$506,4)<>\"http\"),--('Deals'!$A$7:$A$506<>\"\"))"],["=COUNTIFS('Multiples'!$M$7:$M$506,\"YES\",'Multiples'!$D$7:$D$506,\"\")"],["=SUMPRODUCT(--('Multiples'!$M$7:$M$506=\"YES\"),--('Multiples'!$E$7:$E$506<>'Multiples'!$H$7:$H$506))"],["=COUNTIFS('Financials'!$A$7:$A$506,\"<>\",'Financials'!$N$7:$N$506,\"\")"],["=COUNTIFS('Deals'!$AN$7:$AN$506,\"approved\",'Deals'!$D$7:$D$506,\"<>deal\")"],["=SUMPRODUCT(--('Deals'!$A$7:$A$506<>\"\"),--('Deals'!$C$7:$C$506<>\"M&A\"),--('Deals'!$N$7:$N$506<>\"\"))"],["=SUMPRODUCT(--('Deals'!$C$7:$C$506=\"DCM\"),--('Deals'!$G$7:$G$506<>\"\"),--('Deals'!$G$7:$G$506<>\"Not applicable\"),--('Deals'!$G$7:$G$506<>\"Not disclosed\"))"],["=COUNTIF('Multiples'!$M$7:$M$506,\"YES\")"]];
qa.getRange("M7:M17").values=[[0],[0],[0],[0],[0],[0],[0],[0],[0],[0],[">=1"]]; qa.getRange("N7:N16").formulas=Array.from({length:10},(_,i)=>[`=L${7+i}-M${7+i}`]); qa.getRange("O7:O16").values=Array.from({length:10},()=>[0]); qa.getRange("P7:P16").formulas=Array.from({length:10},(_,i)=>[`=IF(ABS(N${7+i})<=O${7+i},\"OK\",\"REVIEW\")`]); qa.getRange("P17").formulas=[["=IF(L17>=1,\"OK\",\"REVIEW\")"]];
qa.getRange("K19:O19").merge();qa.getRange("K19").values=[["Overall model status"]];qa.getRange("P19").formulas=[["=IF(COUNTIF(P7:P17,\"REVIEW\")=0,\"OK\",\"REVIEW\")"]];qa.getRange("K19:P19").format={fill:C.navy,font:{color:C.white,bold:true},borders:{preset:"outside",style:"thin",color:C.border}};qa.getRange("P7:P19").conditionalFormats.add("containsText",{text:"OK",format:{fill:C.paleGreen,font:{color:"#006100",bold:true}}});qa.getRange("P7:P19").conditionalFormats.add("containsText",{text:"REVIEW",format:{fill:C.paleRed,font:{color:C.red,bold:true}}});
setWidths(qa,[28,14,24,30,18,13,50,14,55,3,30,12,12,12,12,14],Math.max(sourceRows.length+7,21)); qa.freezePanes.freezeRows(6);

await fs.mkdir(path.dirname(outputPath),{recursive:true});
const workbookFile=await SpreadsheetFile.exportXlsx(wb); await workbookFile.save(outputPath);
await fs.writeFile(path.join(root,"output","build_manifest.json"),JSON.stringify({build_id:buildId,dataset_sha256:datasetSha256,record_count:rows.length,generated_at:new Date().toISOString()},null,2)+"\n","utf8");
const inspection=await wb.inspect({kind:"sheet,table,formula",maxChars:8000,tableMaxRows:5,tableMaxCols:12,options:{maxResults:160}}); console.log(inspection.ndjson||String(inspection));
const errorScan=await wb.inspect({kind:"match",searchTerm:"#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",options:{useRegex:true,maxResults:100},summary:"final formula error scan",maxChars:4000}); const errorText=errorScan.ndjson||String(errorScan); if(!errorText.includes("matched 0")&&!errorText.includes("0 entries")) throw new Error(`Workbook formula error detected: ${errorText}`);
await fs.mkdir(qaDir,{recursive:true});
for(const name of ["Summary","Deals","Financials","Multiples","Sources & QA"]){const preview=await wb.render({sheetName:name,autoCrop:"all",scale:1,format:"png"});await fs.writeFile(path.join(qaDir,`${name.replaceAll(" ","_").replaceAll("&","and")}.png`),new Uint8Array(await preview.arrayBuffer()));}
console.log(`Workbook created: ${outputPath}`); console.log(`QA renders: ${qaDir}`);
