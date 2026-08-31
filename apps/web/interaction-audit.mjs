/**
 * Interaction audit.
 *
 * Enumerates every interactive element on every screen and reports what it is
 * wired to. The question this answers is not "does the page render" but
 * "is there a control here that does nothing when clicked".
 *
 * It flags:
 *   - buttons with no onClick, no form submit, and no href
 *   - links pointing at a route that does not exist
 *   - controls that are permanently disabled with no explanation
 *
 *   node interaction-audit.mjs
 */

import { chromium } from "@playwright/test";
import { execFileSync } from "node:child_process";

const WEB = process.env.WEB ?? "http://localhost:3000";

function sql(q) {
  return execFileSync("psql", ["-d", "opportunity_agent", "-tAc", q], { encoding: "utf8" }).trim();
}

const oppId = sql("select id from opportunities order by created_at limit 1");
const facultyId = sql("select id from faculty limit 1");
const appId = sql("select id from applications limit 1");

const SCREENS = [
  { name: "Overview", url: "/" },
  { name: "Opportunities", url: "/opportunities" },
  { name: "Opportunity panel", url: `/opportunities?id=${oppId}` },
  { name: "Research", url: "/research" },
  { name: "Lab profile", url: `/research/${facultyId}` },
  { name: "Applications", url: "/applications" },
  ...(appId ? [{ name: "Application kit", url: `/applications/${appId}` }] : []),
  { name: "Resumes", url: "/resumes" },
  { name: "Profile", url: "/profile" },
  { name: "Settings", url: "/settings" },
  { name: "Onboarding", url: "/onboarding" },
];

const KNOWN_ROUTES = [
  "/", "/opportunities", "/research", "/applications", "/resumes", "/profile",
  "/settings", "/onboarding",
];

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

const problems = [];
let totalControls = 0;

for (const screen of SCREENS) {
  await page.goto(`${WEB}${screen.url}`, { waitUntil: "networkidle" });
  await page.waitForTimeout(1800);

  const found = await page.evaluate(() => {
    const out = [];
    const react = (el) =>
      Object.keys(el).some((k) => k.startsWith("__reactProps$") || k.startsWith("__reactFiber$"));
    const propsOf = (el) => {
      const key = Object.keys(el).find((k) => k.startsWith("__reactProps$"));
      return key ? el[key] : null;
    };

    for (const el of document.querySelectorAll("button, a, [role=button], [role=switch], summary")) {
      const rect = el.getBoundingClientRect();
      const visible = rect.width > 0 && rect.height > 0;
      const props = propsOf(el);
      const label =
        (el.getAttribute("aria-label") || el.textContent || "").replace(/\s+/g, " ").trim().slice(0, 60);
      out.push({
        tag: el.tagName.toLowerCase(),
        label,
        visible,
        disabled: el.hasAttribute("disabled") || el.getAttribute("aria-disabled") === "true",
        href: el.getAttribute("href"),
        type: el.getAttribute("type"),
        hasOnClick: Boolean(props && (props.onClick || props.onChange || props.onSubmit)),
        insideForm: Boolean(el.closest("form")),
        isReact: react(el),
        // Our Tooltip renders on hover rather than via the title attribute, so
        // look for a wrapper that would explain a disabled state.
        title:
          el.getAttribute("title") ||
          (el.closest("span")?.previousElementSibling ? "wrapped" : "") ||
          (el.parentElement?.matches("span.relative") ? "tooltip" : ""),
      });
    }
    for (const el of document.querySelectorAll("select, input[type=checkbox], input[type=radio], input[type=file]")) {
      const props = propsOf(el);
      out.push({
        tag: el.tagName.toLowerCase() + (el.getAttribute("type") ? `[${el.getAttribute("type")}]` : ""),
        label: (el.getAttribute("aria-label") || el.getAttribute("name") || "").slice(0, 60),
        visible: el.getBoundingClientRect().width > 0,
        disabled: el.hasAttribute("disabled"),
        href: null,
        hasOnClick: Boolean(props && (props.onChange || props.onClick)),
        insideForm: Boolean(el.closest("form")),
        isReact: true,
        title: "",
      });
    }
    return out;
  });

  const visible = found.filter((c) => c.visible);
  totalControls += visible.length;

  for (const c of visible) {
    const isSubmit = c.type === "submit" || (c.insideForm && c.tag === "button" && !c.type);
    const inert =
      !c.hasOnClick && !c.href && !isSubmit && c.tag !== "summary" && !c.disabled;
    if (inert) {
      problems.push({
        screen: screen.name,
        label: c.label || "(no label)",
        issue: "no handler, no href, not a submit — clicking does nothing",
      });
    }
    if (c.href && c.href.startsWith("/")) {
      const base = c.href.split("?")[0].replace(/\/$/, "") || "/";
      const known =
        KNOWN_ROUTES.includes(base) ||
        base.startsWith("/research/") ||
        base.startsWith("/applications/") ||
        base.startsWith("/opportunities");
      if (!known) {
        problems.push({ screen: screen.name, label: c.label, issue: `links to unknown route ${base}` });
      }
    }
    if (c.disabled && !c.title) {
      problems.push({
        screen: screen.name,
        label: c.label || "(no label)",
        issue: "disabled with no tooltip explaining why",
      });
    }
    if (!c.label) {
      problems.push({ screen: screen.name, label: `<${c.tag}>`, issue: "no accessible name" });
    }
  }

  console.log(`\x1b[1m${screen.name}\x1b[0m — ${visible.length} interactive controls`);
}

await browser.close();

console.log(`\n\x1b[1m${totalControls} controls checked, ${problems.length} problems\x1b[0m`);
const byScreen = new Map();
for (const p of problems) {
  if (!byScreen.has(p.screen)) byScreen.set(p.screen, []);
  byScreen.get(p.screen).push(p);
}
for (const [screen, list] of byScreen) {
  console.log(`\n\x1b[33m${screen}\x1b[0m`);
  for (const p of list) console.log(`  · ${p.label}  —  ${p.issue}`);
}
process.exit(problems.length ? 1 : 0);
