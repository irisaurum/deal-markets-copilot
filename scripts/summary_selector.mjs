import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";


const scriptsDir = path.dirname(fileURLToPath(import.meta.url));
const selectorPath = path.join(scriptsDir, "select_summary_deals.py");


export function selectSummaryDeals(rows, limit = 10) {
  const result = spawnSync(
    process.env.PYTHON || "python3",
    [selectorPath, String(limit)],
    {
      input: JSON.stringify(rows),
      encoding: "utf8",
      maxBuffer: 16 * 1024 * 1024,
    },
  );
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(`Canonical Summary selector failed: ${result.stderr.trim()}`);
  }
  return JSON.parse(result.stdout);
}
