/**
 * Injected on demand by the popup — never declaratively, never on a timer.
 *
 * HARD LIMITS (see README.md and the audit in
 * data/harvest/recon/handshake-integration.json):
 *   - never stores or asks for a SUNet password, Duo code or any credential
 *   - never automates SSO/SAML or two-step, and never touches a Cloudflare check
 *   - never clicks Apply, Quick Apply, Submit Application or Step 2, and never
 *     answers the "Did you apply to this job?" prompt
 *   - reads only what the signed-in student can already see, only when asked
 *   - sends data only to the student's own local Trellis instance
 */

(() => {
  const MODE = window.__TRELLIS_MODE__ ?? "job";
  const src = chrome.runtime.getURL("extract.js");

  return import(src)
    .then((mod) => {
      if (MODE === "list") {
        return { mode: "list", items: mod.extractList(document, location.href) };
      }
      return { mode: "job", items: [mod.extractJob(document, location.href)] };
    })
    .catch((error) => ({
      mode: MODE,
      items: [],
      // Surfaced in the popup. Silence here would look like a broken button.
      error: error && error.message ? error.message : String(error),
    }));
})();
