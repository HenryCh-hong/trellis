/**
 * Screenshot every screen with real data, at several widths.
 *
 *   node shots.mjs           # 1440 only
 *   node shots.mjs responsive
 */

import { chromium } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { mkdirSync } from "node:fs";

const WEB = process.env.WEB ?? "http://localhost:3000";
const OUT = "/tmp/trellis-shots";
mkdirSync(OUT, { recursive: true });

const sql = (q) =>
  execFileSync("psql", ["-d", "opportunity_agent", "-tAc", q], { encoding: "utf8" }).trim();

// Pick rows that actually exercise the interesting states.
const topOpp = sql(`
  select o.id from opportunities o join opportunity_matches m on m.opportunity_id=o.id
  order by m.fit_score desc limit 1`);
const topFaculty = sql(`
  select o.faculty_id from opportunities o join opportunity_matches m on m.opportunity_id=o.id
  where o.faculty_id is not null order by m.fit_score desc limit 1`);
const appId = sql("select id from applications order by updated_at desc limit 1");

const SCREENS = [
  ["overview", "/"],
  ["opportunities", "/opportunities"],
  ["opportunity-detail", `/opportunities?id=${topOpp}`],
  ["research", "/research"],
  ["lab-detail", `/research/${topFaculty}`],
  ["applications", "/applications"],
  ...(appId ? [["application-kit", `/applications/${appId}`]] : []),
  ["resumes", "/resumes"],
  ["profile", "/profile"],
  ["settings", "/settings"],
  ["onboarding", "/onboarding"],
];

const WIDTHS = process.argv.includes("responsive")
  ? [1440, 1280, 1024, 768]
  : [1440];

const browser = await chromium.launch();
for (const width of WIDTHS) {
  const page = await browser.newPage({ viewport: { width, height: 900 } });
  for (const [name, url] of SCREENS) {
    await page.goto(`${WEB}${url}`, { waitUntil: "networkidle" });
    await page.waitForTimeout(2200);
    const file = WIDTHS.length > 1 ? `${name}-${width}.png` : `${name}.png`;
    await page.screenshot({ path: `${OUT}/${file}`, fullPage: false });
    // Horizontal overflow is the classic responsive break; check it here.
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth + 2,
    );
    console.log(`${width}  ${name.padEnd(20)} ${overflow ? "\x1b[31mHORIZONTAL OVERFLOW\x1b[0m" : "ok"}`);
  }
  await page.close();
}
await browser.close();
console.log(`\nwrote ${OUT}`);
