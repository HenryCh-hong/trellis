# Trellis — Handshake import (Chrome MV3)

Most Stanford student jobs are posted to Handshake, which sits behind Stanford
SSO and Duo two-step. Trellis will not sign in for you and will not scrape
Handshake from its backend, so this extension is the only path those jobs take
into the app: it reads the page **you** are already looking at, in **your**
already-authenticated tab, when **you** click it.

## Install

1. `chrome://extensions` → enable Developer mode → **Load unpacked**
2. Choose `apps/extension/`
3. Open the extension's options and point it at your Trellis API
   (default `http://127.0.0.1:8000`)

## Use

Open a Handshake job page, click the extension, then:

- **Read this job** — extracts the single posting you are viewing.
- **Scan this results page** — extracts the visible result rows (title, employer, link).

Everything extracted is shown to you in an editable form first. Nothing is sent
until you press **Import**, and it is sent only to your own local Trellis.

## What it does not do

These are hard limits, enforced by the code and by the permission set:

- **No credentials.** There is no password field. It never stores, requests or
  transmits your SUNet password or Duo codes.
- **No login automation.** It never drives SSO/SAML or two-step, never replays a
  session, never exfiltrates cookies.
- **No bot-check evasion.** It stays inert on Cloudflare interstitials and
  CAPTCHAs. Defeating those is an attack on the platform, not a feature.
- **No submissions.** It never clicks Apply, Quick Apply, Submit Application or
  "Step 2: External Application", and never answers Handshake's
  "Did you apply to this job?" prompt. Handshake also auto-blocks accounts past
  300 applications/day — one more reason submission stays manual.
- **No crawling, no bulk collection.** It does not walk result pages unattended
  and the Trellis backend never fetches Handshake at all. Handshake's
  `robots.txt` is `Disallow: /` and its Terms forbid third-party bulk collection
  of job descriptions. Reading the one page you are personally looking at, for
  your own tracking, is the defensible line; enumerating the job graph is not.
- **No institutional API.** Handshake's EDU API is issued to the school, not to
  students or third-party apps. We do not use it and will never ask you for
  school API credentials.

## Permissions, and why each is needed

| Permission | Why |
|---|---|
| `activeTab` | Read the one tab you clicked on, only after you click |
| `scripting` | Inject the extractor on demand — there is no always-on content script |
| `storage` | Remember your Trellis API address |
| `host_permissions: https://*.joinhandshake.com/*` | Scoped to Handshake only — not `<all_urls>` |

No `cookies` permission. No background page. No remote code.

## Extraction strategy

No stable logged-in CSS selectors for Handshake are publicly verifiable, so this
extension does not hard-code any. It reads, in descending order of reliability:

1. JSON-LD `JobPosting` (gives `datePosted` / `validThrough` when present)
2. Handshake's own `data-knockout-props` blob on legacy pages
3. The document `<title>` (`Title | Employer | Handshake`)
4. Label-based heuristics over visible text (`Job Type:`, `Apply by:` …)

Each field degrades independently. A field the page does not state comes back
`null` and is shown as *not found on the page* — never guessed. Pay is the
sharpest case: on many postings the rate exists only as prose inside the
employer's description, so it is reported only when the page actually labels it.
`test/extract.test.js` pins that behaviour.

## Tests

```bash
npm install --no-save jsdom
npm test
```

Fixtures are hand-authored from the documented page *shapes*, not fetched from
Handshake.
