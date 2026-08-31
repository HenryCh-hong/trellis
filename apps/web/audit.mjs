/**
 * Reality check.
 *
 * Drives the real UI in a real browser against the real API and the real
 * database. Every assertion here is about observable behaviour a user could
 * see — not about whether a function returns something.
 *
 * The rule this file enforces: a UI that says something happened must be
 * backed by a row in Postgres after a full page reload.
 *
 *   node scripts/audit/audit.mjs            # run everything
 *   node scripts/audit/audit.mjs profile    # run one group
 */

import { chromium } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const WEB = process.env.WEB ?? "http://localhost:3000";
const API = process.env.API ?? "http://127.0.0.1:8000";
const HERE = path.dirname(fileURLToPath(import.meta.url));

const results = [];
let group = "";

function sql(query) {
  return execFileSync("psql", ["-d", "opportunity_agent", "-tAc", query], {
    encoding: "utf8",
  }).trim();
}

function record(name, status, detail) {
  results.push({ group, name, status, detail });
  const mark = { PASS: "\x1b[32m✓\x1b[0m", FAIL: "\x1b[31m✗\x1b[0m", MANUAL: "\x1b[33m⚑\x1b[0m", INFO: "·" }[status];
  console.log(`  ${mark} ${name}${detail ? `\n      ${detail}` : ""}`);
}

async function check(name, fn) {
  try {
    const detail = await fn();
    record(name, "PASS", detail);
  } catch (error) {
    record(name, "FAIL", error.message.split("\n")[0].slice(0, 300));
  }
}

function assert(cond, message) {
  if (!cond) throw new Error(message);
}

function head(title) {
  group = title;
  console.log(`\n\x1b[1m${title}\x1b[0m`);
}

/* ------------------------------------------------------------------ tests */

async function profileGroup(page) {
  head("Profile — does editing actually persist?");

  const stamp = `Symbolic Systems ${Date.now() % 100000}`;

  await check("major edit survives a full reload and reaches Postgres", async () => {
    // This edits the student's real profile, so capture the true value and put
    // it back. An audit that leaves test data behind corrupts the thing it is
    // meant to be checking.
    const original = sql(`select coalesce(major,'') from student_profiles limit 1`);
    await page.goto(`${WEB}/profile`, { waitUntil: "networkidle" });
    const major = page.locator('input').filter({ hasNot: page.locator('[type=number]') }).nth(2);
    // Find the Major field by its label rather than position.
    const field = page.locator("label", { hasText: /^Major$/ }).locator("input");
    await field.waitFor({ state: "visible", timeout: 15000 });
    await field.fill(stamp);
    await field.blur();
    await page.waitForTimeout(1200);

    const inDb = sql(`select major from student_profiles limit 1`);
    assert(inDb === stamp, `DB has "${inDb}", expected "${stamp}"`);

    await page.reload({ waitUntil: "networkidle" });
    const after = await page.locator("label", { hasText: /^Major$/ }).locator("input").inputValue();
    assert(after === stamp, `after reload the field shows "${after}"`);
    void major;
    sql(`update student_profiles set major = ${original ? `'${original.replace(/'/g, "''")}'` : "null"}`);
    return `DB and UI both show "${stamp}" after reload, original major restored`;
  });

  await check("adding a research interest persists", async () => {
    const label = `robot learning ${Date.now() % 10000}`;
    await page.goto(`${WEB}/profile`, { waitUntil: "networkidle" });
    const input = page.getByLabel("Add a research interest");
    await input.waitFor({ state: "visible", timeout: 15000 });
    await input.fill(label);
    await input.press("Enter");
    await page.waitForTimeout(1500);

    const n = Number(sql(`select count(*) from profile_research_interests where label='${label}'`));
    assert(n === 1, `expected 1 row in profile_research_interests, found ${n}`);

    await page.reload({ waitUntil: "networkidle" });
    await page.getByText(label, { exact: false }).first().waitFor({ timeout: 10000 });
    return `"${label}" written to profile_research_interests and visible after reload`;
  });

  await check("removing a research interest persists", async () => {
    const label = sql(
      `select label from profile_research_interests where label like 'robot learning%' limit 1`,
    );
    assert(label, "no test interest to remove");
    await page.goto(`${WEB}/profile`, { waitUntil: "networkidle" });
    const chip = page.locator("span", { hasText: label }).first();
    await chip.waitFor({ timeout: 10000 });
    await chip.getByRole("button", { name: `Remove ${label}` }).click();
    await page.waitForTimeout(1500);
    const n = Number(sql(`select count(*) from profile_research_interests where label='${label}'`));
    assert(n === 0, `row still present after remove (${n})`);
    return `"${label}" deleted from the database`;
  });

  await check("adding a skill persists", async () => {
    // Free text normalises onto the canonical vocabulary, so a numeric suffix
    // would collapse onto the same row on a repeat run. Use a word that is not
    // in the vocabulary at all, then remove it so the suite is repeatable.
    const skill = `Zzedge${Date.now() % 100000}`;
    const before = Number(sql(`select count(*) from profile_skills`));
    await page.goto(`${WEB}/profile`, { waitUntil: "networkidle" });
    const input = page.getByLabel("Add a skill");
    await input.waitFor({ state: "visible", timeout: 15000 });
    await input.fill(skill);
    await input.press("Enter");
    await page.waitForTimeout(1800);
    const after = Number(sql(`select count(*) from profile_skills`));
    try {
      assert(after === before + 1, `profile_skills went ${before} -> ${after}`);
    } finally {
      sql(`delete from profile_skills ps using skills s
           where ps.skill_id = s.id and s.label = '${skill}'`);
      sql(`delete from skills where label = '${skill}'`);
    }
    return `profile_skills ${before} -> ${after}, then cleaned up`;
  });

  await check("GPA visibility switch persists (it gates a real behaviour)", async () => {
    const before = sql(`select gpa_is_public from student_profiles limit 1`);
    await page.goto(`${WEB}/profile`, { waitUntil: "networkidle" });
    await page.getByRole("switch").first().click();
    await page.waitForTimeout(1200);
    const after = sql(`select gpa_is_public from student_profiles limit 1`);
    assert(after !== before, `gpa_is_public stayed ${after}`);
    return `gpa_is_public ${before} -> ${after}`;
  });
}

async function resumeGroup(page) {
  head("Resume — real PDF upload, parse, persist, delete");

  await check("uploading a real PDF parses it and stores the file on disk", async () => {
    const before = Number(sql(`select count(*) from resumes`));
    await page.goto(`${WEB}/resumes`, { waitUntil: "networkidle" });
    // Generated on demand: a fixture must not be the user's real resume.
    const fixture = execFileSync(
      "bash",
      [path.join(HERE, "..", "..", "scripts", "audit", "make-fixture-resume.sh")],
      { encoding: "utf8" },
    ).trim();
    await page.locator('input[type=file]').setInputFiles(fixture);
    await page.waitForTimeout(4000);

    const after = Number(sql(`select count(*) from resumes`));
    assert(after === before + 1, `resumes went ${before} -> ${after}`);

    const row = sql(
      `select parse_status||'|'||coalesce(page_count::text,'?')||'|'||coalesce(length(text)::text,'0')||'|'||storage_path
       from resumes order by created_at desc limit 1`,
    ).split("|");
    assert(row[0] === "parsed", `parse_status is ${row[0]}`);
    assert(Number(row[2]) > 200, `only ${row[2]} chars of text extracted`);

    const onDisk = execFileSync("bash", [
      "-lc",
      `test -f /Users/henrych/opportunity-agent/apps/api/storage/resumes/${row[3]} && echo yes || echo no`,
    ], { encoding: "utf8" }).trim();
    assert(onDisk === "yes", "the uploaded file is not on disk");
    return `parsed, ${row[1]} page(s), ${row[2]} chars, file present on disk`;
  });

  await check("uploaded resume survives reload and shows its parsed lines", async () => {
    await page.goto(`${WEB}/resumes`, { waitUntil: "networkidle" });
    const label = sql(`select label from resumes order by created_at desc limit 1`);
    const row = page.getByRole("row", { name: new RegExp(label, "i") }).first();
    await row.waitFor({ timeout: 10000 });
    await row.click();
    await page.waitForTimeout(1500);
    const quoted = sql(
      `select count(*) from resume_highlights h join resumes r on r.id=h.resume_id
       where r.label = '${label.replace(/'/g, "''")}'`,
    );
    assert(Number(quoted) > 0, "no verbatim highlight lines were extracted");
    return `${quoted} verbatim lines extracted and the detail panel opens`;
  });

  await check("the recommended resume is one the user actually uploaded", async () => {
    const rec = sql(`
      select r.label from resume_recommendations rr
      join resumes r on r.id = rr.resume_id
      where rr.rank = 1 limit 1`);
    assert(rec, "no resume recommendation rows exist");
    const uploaded = sql(`select count(*) from resumes where label = '${rec.replace(/'/g, "''")}'`);
    assert(Number(uploaded) === 1, "recommended resume is not an uploaded row");
    return `top recommendation "${rec}" is a real uploaded resume`;
  });

  await check("deleting a resume removes the row and the file", async () => {
    const target = sql(
      `select id||'|'||storage_path||'|'||label from resumes order by created_at desc limit 1`,
    ).split("|");
    await page.goto(`${WEB}/resumes`, { waitUntil: "networkidle" });
    const row = page.getByRole("row", { name: new RegExp(target[2], "i") }).first();
    await row.getByRole("button", { name: "Delete" }).click();
    await row.getByRole("button", { name: "Delete" }).click();
    await page.waitForTimeout(2000);
    const gone = Number(sql(`select count(*) from resumes where id='${target[0]}'`));
    assert(gone === 0, "the resume row is still in the database");
    const onDisk = execFileSync("bash", [
      "-lc",
      `test -f /Users/henrych/opportunity-agent/apps/api/storage/resumes/${target[1]} && echo yes || echo no`,
    ], { encoding: "utf8" }).trim();
    assert(onDisk === "no", "the file is still on disk after delete");
    return "row and file both removed";
  });
}

async function opportunityGroup(page) {
  head("Opportunities — is the table real, and does saving persist?");

  await check("the table renders rows that exist in Postgres", async () => {
    const total = Number(sql(`select count(*) from opportunities`));
    // focus=all: the default narrows to the student's interests, and this check
    // is about the table rendering every row it is given.
    await page.goto(`${WEB}/opportunities?focus=all`, { waitUntil: "networkidle" });
    await page.getByText(/\d+ (tracked|of \d+ shown)/).first().waitFor({ timeout: 15000 });
    // Expired rows are deliberately withheld from the default view, so a row
    // that renders must be a live one. Picking any row would test the wrong thing.
    const title = sql(
      `select title from opportunities where deadline_state is distinct from 'expired' order by created_at limit 1`,
    );
    const shown = await page.getByText(title.slice(0, 40), { exact: false }).count();
    assert(shown > 0, `"${title.slice(0, 40)}" not found in the rendered table`);

    // And the withholding is real: an expired row is absent until asked for.
    const expired = sql(
      `select title from opportunities where deadline_state = 'expired' order by created_at limit 1`,
    );
    if (expired) {
      const hidden = await page.getByText(expired.slice(0, 40), { exact: false }).count();
      assert(hidden === 0, `expired "${expired.slice(0, 40)}" is showing in the default view`);
      // Brought back the way a person would: the "Show them" affordance next to
      // the count, not a URL only this script knows about.
      const show = page.getByRole("button", { name: /show them/i }).first();
      assert(await show.count(), "nothing on screen offers to show the expired rows");
      await show.click();
      await page.waitForTimeout(1800);
      const back = await page.getByText(expired.slice(0, 40), { exact: false }).count();
      assert(back > 0, `expired "${expired.slice(0, 40)}" cannot be brought back into view`);
    }
    return `${total} in DB; a live row renders, an expired row is withheld and recoverable`;
  });

  await check("deadline sort puts real upcoming dates first and overdue last", async () => {
    await page.goto(`${WEB}/opportunities?sort=deadline`, { waitUntil: "networkidle" });
    await page.waitForTimeout(2500);
    const api = await (await fetch(`${API}/api/opportunities?sort=deadline&limit=100`)).json();
    const order = api.items.map((i) => i.urgency);
    const firstOverdue = order.indexOf("overdue");
    const lastDated = order.map((u, i) => (["urgent", "soon", "later"].includes(u) ? i : -1)).filter((i) => i >= 0).pop();
    assert(
      firstOverdue === -1 || lastDated === undefined || firstOverdue > lastDated,
      `an overdue row (index ${firstOverdue}) sorts before a live one (index ${lastDated})`,
    );
    const unknownBeforeDated = order.indexOf("unknown") !== -1 && order.indexOf("unknown") < (lastDated ?? 1e9);
    assert(!unknownBeforeDated, "an unknown deadline sorts ahead of a real dated one");
    return `${api.items.length} rows: dated → rolling → unknown → overdue`;
  });

  await check("focus defaults to the student's interests and is reversible", async () => {
    const all = await (await fetch(`${API}/api/opportunities?limit=1`)).json();
    const focused = await (await fetch(`${API}/api/opportunities?focus=interests&limit=200`)).json();
    assert(focused.total > 0, "the interests filter hides everything");
    assert(focused.total < all.total, "the interests filter narrows nothing");
    const unexplained = focused.items.filter((i) => !i.relevance_reason);
    assert(
      unexplained.length === 0,
      `${unexplained.length} rows are in the filtered view with no stated reason`,
    );
    await page.goto(`${WEB}/opportunities`, { waitUntil: "networkidle" });
    await page.waitForTimeout(2000);
    const body = await page.locator("body").innerText();
    const header = /(\d+) of (\d+) shown/.exec(body);
    assert(header, "the header does not say how much is being hidden");
    const [, visible, scope] = header.map(Number);
    assert(Number(scope) === all.total, `the header counts ${scope} against a real total of ${all.total}`);
    assert(Number(visible) <= all.total, "the header shows more rows than exist");
    // Anything subtracted from the total has to be named, not silently dropped.
    const withheld = Number(scope) - Number(visible);
    if (withheld > 0) {
      assert(
        /expired hidden|hidden by you/.test(body),
        `${withheld} rows are missing from the count with no stated reason`,
      );
    }
    return `${focused.total} of ${all.total}, every row explains why it is there`;
  });

  await check("saving an opportunity from the detail panel persists", async () => {
    const id = sql(`select id from opportunities where status='new' order by created_at limit 1`);
    assert(id, "no 'new' opportunity to save");
    await page.goto(`${WEB}/opportunities?focus=all&id=${id}`, { waitUntil: "networkidle" });
    await page.waitForTimeout(2000);
    // Change status through the panel's status control.
    const select = page.locator('aside select, aside [role=combobox]').last();
    if (await select.count()) {
      await select.selectOption("saved").catch(() => {});
      await page.waitForTimeout(1500);
    }
    const status = sql(`select status from opportunities where id='${id}'`);
    try {
      assert(status === "saved", `status is "${status}" after using the panel control`);
    } finally {
      // Put it back: repeated runs would otherwise leave a growing pile of
      // "saved" rows in the student's real list.
      sql(`update opportunities set status='new' where id='${id}'`);
    }
    return `opportunity ${id.slice(0, 8)} saved in Postgres, then restored`;
  });
}

async function applicationGroup(page) {
  head("Applications — status changes must survive a reload");

  await check("status change persists to Postgres and to the opportunity", async () => {
    const app = sql(`select id||'|'||opportunity_id||'|'||status from applications limit 1`);
    assert(app, "no application exists to exercise");
    const [id, oppId] = app.split("|");
    await page.goto(`${WEB}/applications/${id}`, { waitUntil: "networkidle" });
    await page.waitForTimeout(2000);
    // Start from a known state so the check is repeatable rather than dependent
    // on whatever the previous run left behind.
    sql(`update applications set status='preparing' where id='${id}'`);
    sql(`update opportunities set status='preparing' where id='${oppId}'`);
    await page.reload({ waitUntil: "networkidle" });
    await page.waitForTimeout(1500);

    const select = page.locator("aside select").first();
    await select.waitFor({ timeout: 10000 });
    await select.selectOption("ready_to_apply");
    await page.waitForTimeout(2200);

    const after = sql(`select status from applications where id='${id}'`);
    const oppStatus = sql(`select status from opportunities where id='${oppId}'`);
    assert(after === "ready_to_apply", `application status is "${after}"`);
    assert(oppStatus === after, `opportunity shows "${oppStatus}" but application shows "${after}"`);
    return `preparing -> ready_to_apply, written through to the opportunity`;
  });
}

async function reminderGroup(page) {
  head("Reminders — does 'Add reminder' create anything?");

  await check("Add reminder creates a real reminder row", async () => {
    const before = Number(sql(`select count(*) from reminders`));
    const id = sql(`
      select o.id from opportunities o
      where o.deadline is not null
        and o.deadline >= current_date
        and o.deadline_state is distinct from 'expired'
        and not exists (select 1 from reminders r where r.opportunity_id = o.id)
      order by o.deadline limit 1`);
    assert(id, "every dated opportunity already has a reminder");
    await page.goto(`${WEB}/opportunities?focus=all&id=${id}`, { waitUntil: "networkidle" });
    await page.waitForTimeout(2500);
    const btn = page.getByRole("button", { name: /add reminder/i }).first();
    const exists = await btn.count();
    assert(exists > 0, "no 'Add reminder' control found on an opportunity with a deadline");
    const disabled = await btn.isDisabled().catch(() => false);
    assert(!disabled, "the 'Add reminder' control is present but disabled");
    await btn.click();
    await page.waitForTimeout(1500);

    // The button opens the full flow; the user then chooses offsets and creates.
    const create = page.getByRole("button", { name: /create reminder/i });
    await create.waitFor({ timeout: 10000 });
    await create.click();
    await page.waitForTimeout(2500);

    const after = Number(sql(`select count(*) from reminders`));
    assert(after === before + 1, `reminders went ${before} -> ${after} — the flow did nothing`);

    // And the reminder must be exportable, or it is a dead end.
    // A real download anchor, not a button — the browser saves the file.
    const download = page.getByRole("link", { name: /download \.ics/i });
    await download.waitFor({ timeout: 10000 });
    const offsets = sql(
      `select array_to_string(offsets_days,',') from reminders order by created_at desc limit 1`,
    );
    // Leave the fixture as we found it, or a later run has no dated opportunity
    // left without a reminder.
    sql(`delete from reminders where opportunity_id = '${id}'`);
    return `reminders ${before} -> ${after}, offsets [${offsets}], export offered`;
  });

  await check("the .ics export is a real calendar file with real alarms", async () => {
    const id = sql(`select id from reminders limit 1`);
    assert(id, "no reminder to export");
    const res = await fetch(`${API}/api/reminders/${id}/export.ics`);
    const body = await res.text();
    assert(res.ok, `export returned ${res.status}`);
    assert(body.includes("BEGIN:VCALENDAR"), "not an iCalendar document");
    const alarms = (body.match(/BEGIN:VALARM/g) ?? []).length;
    assert(alarms >= 1, "no VALARM in the exported file");
    return `${alarms} alarms, ${body.length} bytes of valid iCalendar`;
  });
}

async function researchGroup(page) {
  head("Research — are the labs, papers and sources real?");

  await check("lead cards come from the database, with real evidence", async () => {
    await page.goto(`${WEB}/research`, { waitUntil: "networkidle" });
    await page.waitForTimeout(3000);
    const dbCount = Number(sql(`select count(*) from opportunities where faculty_id is not null`));
    const api = await (await fetch(`${API}/api/research/leads?limit=300`)).json();
    assert(api.total === dbCount, `API reports ${api.total}, DB has ${dbCount}`);
    const withEvidence = api.items.filter((i) => i.evidence_count > 0).length;
    assert(withEvidence === api.items.length, `${api.items.length - withEvidence} leads have no evidence`);
    return `${api.total} leads, every one backed by evidence`;
  });

  await check("evidence URLs are real, reachable pages", async () => {
    const urls = sql(`
      select url from research_evidence
      where url is not null and url like 'http%'
      order by random() limit 5`).split("\n").filter(Boolean);
    assert(urls.length >= 3, "not enough evidence URLs to sample");
    // A DOI is checked WITHOUT following the redirect on purpose. doi.org answers
    // 404 for a DOI that was never registered and 30x for one that was, so the
    // redirect itself is the proof. Following it instead measures whether ACM's
    // bot filter is in a good mood, which says nothing about whether we made the
    // citation up. Everything else is fetched normally and must answer 2xx.
    const codes = [];
    for (const u of urls) {
      const isDoi = /^https?:\/\/(dx\.)?doi\.org\//i.test(u);
      const code = execFileSync("bash", [
        "-lc",
        `curl -s -o /dev/null -w '%{http_code}' -A 'Mozilla/5.0' -m 25 ${isDoi ? "" : "-L"} '${u.replace(/'/g, "")}' || echo 000`,
      ], { encoding: "utf8" }).trim();
      const good = isDoi ? /^3/.test(code) || /^2/.test(code) : /^2/.test(code);
      codes.push(`${good ? "ok" : "BAD"} ${code} ${u.slice(0, 58)}`);
    }
    const ok = codes.filter((c) => c.startsWith("ok")).length;
    assert(
      ok === codes.length,
      `${codes.length - ok}/${codes.length} evidence URLs do not resolve:\n      ${codes.join("\n      ")}`,
    );
    return `${ok}/${codes.length} sampled evidence URLs resolve (DOIs verified as registered)`;
  });

  await check("a lab profile shows current direction with an honest certainty", async () => {
    const fid = sql(`
      select f.id from faculty f
      where array_length(f.current_direction,1) > 0 limit 1`);
    await page.goto(`${WEB}/research/${fid}`, { waitUntil: "networkidle" });
    await page.getByText("Current research direction").waitFor({ timeout: 15000 });
    const body = await page.locator("body").innerText();
    assert(/Verified|Likely|Inferred|Unknown/.test(body), "no certainty word is shown");
    assert(body.includes("Evidence"), "no evidence section rendered");
    return "direction, certainty word and evidence timeline all present";
  });

  await check("an outreach lead never offers 'Apply now'", async () => {
    const fid = sql(`
      select o.faculty_id from opportunities o
      where o.type='research_outreach' and o.faculty_id is not null limit 1`);
    await page.goto(`${WEB}/research/${fid}`, { waitUntil: "networkidle" });
    await page.waitForTimeout(2000);
    const body = (await page.locator("body").innerText()).toLowerCase();
    assert(!body.includes("apply now"), "an outreach lead shows 'Apply now'");
    assert(
      body.includes("no advertised") || body.includes("outreach"),
      "the page does not say this is an outreach lead",
    );
    return "shows outreach framing, no apply CTA";
  });
}

async function discoveryGroup() {
  head("Discovery — does Run Discovery actually hit the network?");

  await check("a jobs run fetches real pages and reports real counts", async () => {
    const started = new Date().toISOString();
    const res = await fetch(`${API}/api/searches/discover`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind: "jobs" }),
    });
    const run = await res.json();
    let status = "running";
    let detail = {};
    for (let i = 0; i < 60 && (status === "running" || status === "queued"); i++) {
      await new Promise((r) => setTimeout(r, 3000));
      detail = await (await fetch(`${API}/api/runs/${run.id}`)).json();
      status = detail.status;
    }
    assert(status !== "running", "the run never finished (still running after 3 minutes)");
    assert(status !== "failed", `the run failed: ${detail.error}`);
    assert(detail.documents_fetched > 0, "zero documents fetched — nothing was actually retrieved");
    const touched = Number(
      sql(`select count(*) from opportunities where last_checked_at > '${started}'`),
    );
    assert(touched > 0, "no opportunity row was touched by the run");
    return `${status}: ${detail.documents_fetched} pages fetched, ${detail.created_count} new, ${detail.updated_count} updated, ${touched} rows touched`;
  });

  await check("re-running does not duplicate", async () => {
    const before = Number(sql(`select count(*) from opportunities`));
    const res = await fetch(`${API}/api/searches/discover`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind: "jobs" }),
    });
    const run = await res.json();
    let status = "running";
    for (let i = 0; i < 60 && (status === "running" || status === "queued"); i++) {
      await new Promise((r) => setTimeout(r, 3000));
      status = (await (await fetch(`${API}/api/runs/${run.id}`)).json()).status;
    }
    const after = Number(sql(`select count(*) from opportunities`));
    assert(after === before, `opportunity count went ${before} -> ${after} on a repeat run`);
    return `count stable at ${after} across a repeat run`;
  });
}

async function honestyGroup(page) {
  head("Honesty — does the UI ever assert something it cannot support?");

  await check("no opportunity shows a deadline it did not read from a source", async () => {
    const bad = Number(
      sql(`select count(*) from opportunities where deadline is not null and deadline_confidence = 0`),
    );
    assert(bad === 0, `${bad} deadlines asserted at zero confidence`);
    return "every displayed deadline has non-zero confidence";
  });

  await check("no faculty email is shown without a source page", async () => {
    const bad = Number(sql(`select count(*) from faculty where email is not null and email_source_url is null`));
    assert(bad === 0, `${bad} emails lack a source URL`);
    return "every stored email cites the page it was read from";
  });

  await check("an unknown deadline renders as Unknown, not as a date", async () => {
    const id = sql(`select id from opportunities where deadline is null and deadline_type='unknown' limit 1`);
    assert(id, "no unknown-deadline opportunity to check");
    await page.goto(`${WEB}/opportunities?focus=all&id=${id}`, { waitUntil: "networkidle" });
    await page.waitForTimeout(2000);
    const body = await page.locator("body").innerText();
    assert(body.includes("Unknown"), "the panel does not say Unknown");
    return "renders the word Unknown";
  });
}


/* ------------------------------------------- the daily loop's hard promises */

async function loopGroup(page) {
  head("Daily loop — does it ever manufacture an action?");

  await check("a lead is only an OPENING when a source says so, in words", async () => {
    const rows = sql(`
      select o.id || '|' || o.lead_state || '|' || coalesce(o.lead_state_signals::text,'[]')
      from opportunities o where o.lead_state is not null`).split("\n").filter(Boolean);
    assert(rows.length > 0, "no lead has a stored state");
    let openings = 0;
    for (const row of rows) {
      const [id, state, raw] = row.split("|");
      const signals = JSON.parse(raw);
      // Every signal must cite a page. A claim with no source is a claim we invented.
      for (const sig of signals) {
        assert(sig.source_url, `${state} lead ${id.slice(0, 8)} has a signal with no source URL`);
      }
      if (state !== "opening") continue;
      openings += 1;
      const quoted = signals.some(
        (sig) => /statement|invite|addresses undergraduates/i.test(sig.label || "") && (sig.detail || "").length > 20,
      );
      assert(quoted, `lead ${id.slice(0, 8)} is an OPENING with no quoted statement behind it`);
    }
    return `${rows.length} leads, ${openings} openings, every signal sourced`;
  });

  await check("a lab with nothing current is never upgraded into an action", async () => {
    // The rule the spec is strictest about: no promoting UNKNOWN/WATCH to
    // OUTREACH just so the screen has a button on it.
    const bad = sql(`
      select count(*) from opportunities o
      where o.lead_state in ('outreach','opening')
        and not exists (
          select 1 from research_evidence e
          where e.faculty_id = o.faculty_id and e.year >= ${new Date().getFullYear() - 2})`);
    assert(Number(bad) === 0, `${bad} actionable leads have no evidence in the last 2 years`);

    // And a lab we know is unreachable must not be offered as outreach.
    const retired = sql(`
      select count(*) from opportunities o
      join lab_signals ls on ls.faculty_id = o.faculty_id
      -- a *person* having left, not a 'retired form': the loose word matches
      -- ordinary prose about stale Google Forms and says nothing about the PI.
      where o.lead_state = 'outreach'
        and ls.statement ~* '(retired from (teaching|stanford)|no longer at stanford|has left stanford|is emeritus)'`);
    assert(Number(retired) === 0, `${retired} outreach leads point at someone who has left`);
    return "no lead is actionable without current evidence and a live contact route";
  });

  await check("an expired deadline refuses a reminder, and says why", async () => {
    const id = sql(`select id from opportunities where deadline_state='expired' order by deadline desc limit 1`);
    if (!id) return "no expired opportunity in the corpus to check";
    await page.goto(`${WEB}/opportunities?focus=all&expired=1&id=${id}`, { waitUntil: "networkidle" });
    await page.waitForTimeout(2500);
    const btn = page.getByRole("button", { name: /add reminder/i }).first();
    assert(await btn.count(), "no reminder control on the expired opportunity");
    assert(await btn.isDisabled(), "an expired deadline still offers to remind you about it");
    const body = await page.locator("body").innerText();
    assert(/passed|expired/i.test(body), "the panel does not say the deadline has passed");
    return "refused, with the reason on screen";
  });

  await check("hiding one opportunity does not bury its whole topic", async () => {
    const before = await (await fetch(`${API}/api/opportunities?focus=interests&limit=200`)).json();
    const target = before.items.find((i) => (i.relevance_reason || "").length > 0);
    if (!target) return "no explained row to test against";
    const peers = before.items.filter(
      (i) => i.id !== target.id && i.relevance_reason === target.relevance_reason,
    );
    await fetch(`${API}/api/opportunities/${target.id}/feedback`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ signal: "not_relevant" }),
    });
    try {
      const after = await (await fetch(`${API}/api/opportunities?focus=interests&limit=200`)).json();
      for (const peer of peers) {
        const still = after.items.find((i) => i.id === peer.id);
        assert(still, `hiding one row removed a sibling sharing "${target.relevance_reason}"`);
      }
      return `hid 1 row; ${peers.length} sharing its reason stayed`;
    } finally {
      await fetch(`${API}/api/opportunities/${target.id}/feedback`, { method: "DELETE" });
    }
  });

  await check("every claim on the research page carries a link", async () => {
    const id = sql(`select faculty_id from opportunities where lead_state='opening' and faculty_id is not null limit 1`);
    assert(id, "no opening lead with a faculty record");
    const detail = await (await fetch(`${API}/api/research/faculty/${id}`)).json();
    const ctx = detail.research || detail;
    for (const sig of ctx.lead_state_signals || []) {
      assert(sig.source_url, `signal "${sig.label}" has no source link`);
    }
    for (const dir of ctx.directions || []) {
      for (const ev of dir.evidence || []) {
        assert(ev.source_url || ev.url, `direction "${dir.label}" cites evidence with no link`);
      }
    }
    const fit = detail.fit;
    if (fit) {
      for (const item of fit.strong_overlap || []) {
        assert(item.evidence, `overlap "${item.label}" is asserted with no evidence`);
      }
    }
    return `${(ctx.lead_state_signals || []).length} signals, ${(ctx.directions || []).length} directions, all linked`;
  });
}

/* ------------------------------------------------------------------- main */

const GROUPS = {
  profile: profileGroup,
  resume: resumeGroup,
  opportunity: opportunityGroup,
  application: applicationGroup,
  reminder: reminderGroup,
  research: researchGroup,
  discovery: discoveryGroup,
  honesty: honestyGroup,
  loop: loopGroup,
};

const wanted = process.argv.slice(2);
const toRun = wanted.length ? wanted : Object.keys(GROUPS);

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await context.newPage();
const consoleErrors = [];
page.on("console", (m) => {
  if (m.type() === "error") consoleErrors.push(m.text().slice(0, 200));
});
page.on("pageerror", (e) => consoleErrors.push(`pageerror: ${e.message}`.slice(0, 200)));

for (const name of toRun) {
  const fn = GROUPS[name];
  if (!fn) {
    console.log(`unknown group: ${name}`);
    continue;
  }
  await fn(page);
}

await browser.close();

const pass = results.filter((r) => r.status === "PASS").length;
const fail = results.filter((r) => r.status === "FAIL").length;
console.log(`\n\x1b[1mResult: ${pass} passed, ${fail} failed\x1b[0m`);
if (consoleErrors.length) {
  const unique = [...new Set(consoleErrors)];
  console.log(`\n\x1b[33mBrowser console errors (${unique.length} unique):\x1b[0m`);
  for (const e of unique.slice(0, 12)) console.log(`  ${e}`);
}
process.exit(fail > 0 ? 1 : 0);
