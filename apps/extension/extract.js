/**
 * Handshake extraction.
 *
 * Design constraints, taken from the integration research in
 * data/harvest/recon/handshake-integration.json and from Handshake's own
 * published terms:
 *
 *  - This runs ONLY in a tab the student already has open and is already
 *    logged in to, and only when they click the extension. It is never
 *    injected declaratively and never crawls.
 *  - No stable logged-in CSS selectors are publicly verifiable, so we do not
 *    hard-code any. We read, in order of reliability: embedded JSON
 *    (JSON-LD, then Handshake's own knockout data props), then <title>, then
 *    label-based heuristics over visible text.
 *  - Every field degrades to null on its own. A missing field is null, never
 *    a guess, because the highest-stakes field here (apply-by date) causes
 *    real harm if wrong.
 */

const APPLY_LABELS = {
  "quick apply": "handshake_quick_apply",
  apply: "handshake",
  "apply externally": "external",
};

function textOf(node) {
  return (node?.textContent ?? "").replace(/\s+/g, " ").trim() || null;
}

/** Handshake's legacy pages carry a knockout props blob; the SPA may not. */
export function readKnockoutProps(doc) {
  const holders = doc.querySelectorAll("[data-knockout-props]");
  for (const el of holders) {
    try {
      const parsed = JSON.parse(el.getAttribute("data-knockout-props"));
      if (parsed && typeof parsed === "object") return parsed;
    } catch {
      /* malformed blob: fall through to the next holder */
    }
  }
  return null;
}

export function readJsonLd(doc) {
  for (const script of doc.querySelectorAll('script[type="application/ld+json"]')) {
    try {
      const parsed = JSON.parse(script.textContent);
      const items = Array.isArray(parsed) ? parsed : [parsed];
      const posting = items.find((i) => i && i["@type"] === "JobPosting");
      if (posting) return posting;
    } catch {
      /* ignore malformed JSON-LD */
    }
  }
  return null;
}

/** "Job Type: Full-Time" style rows, and dt/dd or label/value pairs. */
export function readLabelled(doc, labels) {
  const wanted = labels.map((l) => l.toLowerCase());
  const candidates = doc.querySelectorAll("dt, th, strong, b, span, div, li, p");
  for (const node of candidates) {
    const text = textOf(node);
    if (!text) continue;
    const lowered = text.toLowerCase().replace(/[:\s]+$/, "");
    if (!wanted.includes(lowered)) continue;

    const sibling =
      node.nextElementSibling ??
      node.parentElement?.querySelector("dd, td") ??
      null;
    const value = textOf(sibling);
    if (value && value.toLowerCase() !== lowered) return value;
  }
  // Inline "Label: value" inside one node.
  for (const node of candidates) {
    const text = textOf(node);
    if (!text || text.length > 200) continue;
    for (const label of wanted) {
      const m = new RegExp(`^${label}\\s*[:\\-]\\s*(.+)$`, "i").exec(text);
      if (m && m[1].trim()) return m[1].trim();
    }
  }
  return null;
}

export function readApplicationMethod(doc) {
  for (const btn of doc.querySelectorAll('button, a[role="button"], a')) {
    const label = (textOf(btn) ?? "").toLowerCase();
    if (APPLY_LABELS[label]) return APPLY_LABELS[label];
  }
  return null;
}

export function jobIdFromUrl(url) {
  const m = /\/jobs\/(\d+)/.exec(url ?? "");
  return m ? m[1] : null;
}

function titleFromDocumentTitle(doc) {
  // Handshake sets "<Title> | <Employer> | Handshake".
  const raw = (doc.title || "").split("|").map((s) => s.trim()).filter(Boolean);
  if (raw.length >= 2 && raw[raw.length - 1].toLowerCase() === "handshake") {
    return { title: raw[0] || null, employer: raw.length >= 3 ? raw[1] : null };
  }
  return { title: null, employer: null };
}

export function extractJob(doc, url) {
  const ld = readJsonLd(doc);
  const ko = readKnockoutProps(doc);
  const fromTitle = titleFromDocumentTitle(doc);

  const heading = textOf(doc.querySelector("h1"));
  const title = ld?.title ?? heading ?? fromTitle.title ?? null;

  const employer =
    ld?.hiringOrganization?.name ??
    textOf(doc.querySelector('[class*="subtitle"] a[href*="/employers/"]')) ??
    textOf(doc.querySelector('a[href*="/employers/"]')) ??
    fromTitle.employer ??
    null;

  const location =
    ld?.jobLocation?.address?.addressLocality ??
    (Array.isArray(ko?.location_names) ? ko.location_names[0] : null) ??
    readLabelled(doc, ["location"]) ??
    null;

  const description =
    ld?.description ??
    textOf(doc.querySelector(".sanitized-html-container")) ??
    textOf(doc.querySelector('[class*="description"]')) ??
    null;

  return {
    url: url ?? doc.location?.href ?? null,
    external_key: jobIdFromUrl(url ?? doc.location?.href),
    title,
    employer,
    location,
    job_type: readLabelled(doc, ["job type", "employment type"]),
    // Pay is very often only prose inside the employer's description, so we
    // report it only when the page labels it. Never assert a rate we inferred.
    pay: readLabelled(doc, ["pay", "salary", "compensation", "pay range"]),
    posted_at: ld?.datePosted ?? readLabelled(doc, ["posted", "posted on", "apply start date"]),
    apply_by: ld?.validThrough ?? readLabelled(doc, ["apply by", "expires", "expiration", "application deadline"]),
    description,
    application_method: readApplicationMethod(doc),
  };
}

/** Result rows on a jobs list page the student is already viewing. */
export function extractList(doc, baseUrl) {
  const seen = new Set();
  const out = [];
  for (const link of doc.querySelectorAll('a[href*="/jobs/"]')) {
    const href = link.getAttribute("href");
    const id = jobIdFromUrl(href);
    if (!id || seen.has(id)) continue;
    seen.add(id);
    const card = link.closest("article, li, div[class*='card'], div[class*='result']") ?? link;
    out.push({
      url: new URL(href, baseUrl).href,
      external_key: id,
      title: textOf(link) || textOf(card.querySelector("h2, h3")) || null,
      employer: textOf(card.querySelector('a[href*="/employers/"]')),
      location: null,
      job_type: null,
      pay: null,
      posted_at: null,
      apply_by: null,
      description: null,
      application_method: null,
    });
  }
  return out.filter((j) => j.title);
}
