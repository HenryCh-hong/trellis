#!/usr/bin/env bash
# End-to-end smoke test: does the whole vertical slice actually work?
# Run from the repo root:  bash scripts/verify.sh
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API="$ROOT/apps/api"
WEB="$ROOT/apps/web"
BASE="http://127.0.0.1:8000"
PASS=0; FAIL=0

ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; PASS=$((PASS+1)); }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$1"; FAIL=$((FAIL+1)); }
head_() { printf '\n\033[1m%s\033[0m\n' "$1"; }

check() { # check <name> <command...>
  local name="$1"; shift
  if "$@" >/dev/null 2>&1; then ok "$name"; else bad "$name"; fi
}

json() { curl -s --max-time 20 "$BASE$1"; }

# jq is nice but not guaranteed; fall back to python.
jget() { python3 -c "import sys,json;d=json.load(sys.stdin);
import functools
p='''$1'''.split('.')
for k in p:
    if not k: continue
    d = d[int(k)] if k.isdigit() else d.get(k) if isinstance(d,dict) else None
    if d is None: break
print(d if d is not None else '')" 2>/dev/null
}

head_ "1. Database"
check "postgres is accepting connections" pg_isready
for t in faculty opportunities requirements research_evidence lab_signals opportunity_matches; do
  n=$(psql -d opportunity_agent -tAc "select count(*) from $t" 2>/dev/null || echo "ERR")
  if [[ "$n" == "ERR" ]]; then bad "table $t"; else
    if [[ "$n" -gt 0 ]]; then ok "$t: $n rows"; else bad "$t: 0 rows (seed did not load)"; fi
  fi
done

head_ "2. Backend tests"
if (cd "$API" && .venv/bin/python -m pytest -q 2>&1 | tail -3); then ok "pytest"; else bad "pytest"; fi

head_ "3. Lint / typecheck"
if (cd "$API" && .venv/bin/ruff check app >/dev/null 2>&1); then ok "ruff"; else bad "ruff"; fi
if (cd "$WEB" && npx tsc --noEmit >/dev/null 2>&1); then ok "tsc --noEmit"; else bad "tsc --noEmit"; fi

head_ "4. API"
if ! curl -sf --max-time 5 "$BASE/api/health" >/dev/null 2>&1; then
  echo "  starting uvicorn..."
  (cd "$API" && .venv/bin/uvicorn app.main:app --port 8000 >/tmp/trellis-api.log 2>&1 &)
  for _ in $(seq 1 25); do sleep 1; curl -sf "$BASE/api/health" >/dev/null 2>&1 && break; done
  STARTED=1
fi

if curl -sf --max-time 5 "$BASE/api/health" >/dev/null 2>&1; then
  ok "GET /api/health"
  echo "     provider: $(json /api/health | jget llm_provider)"
else
  bad "GET /api/health — see /tmp/trellis-api.log"
fi

for ep in "/api/overview" "/api/opportunities?limit=5" "/api/research/leads" "/api/research/topics" "/api/resumes" "/api/applications" "/api/sources" "/api/provenance" "/api/reminders/providers"; do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$BASE$ep")
  if [[ "$code" == "200" ]]; then ok "GET $ep"; else bad "GET $ep -> HTTP $code"; fi
done

head_ "5. Data shape (the honesty checks)"
TOTAL=$(json "/api/opportunities?limit=1" | jget total)
[[ -n "$TOTAL" && "$TOTAL" -gt 0 ]] && ok "opportunities returned: $TOTAL" || bad "no opportunities from the API"

# Every research lead must carry evidence, and no lead may claim OPENING without a source.
# Only faculty-derived leads are expected to carry evidence. The 16 formal
# programmes (CURIS, VPUE grants, Bio-X) have no PI attached and correctly have none.
psql -d opportunity_agent -tAc "
select count(*) from opportunities o
where o.type in ('research_opening','research_outreach')
  and o.faculty_id is not null
  and not exists (select 1 from research_evidence e where e.faculty_id = o.faculty_id)
" 2>/dev/null | { read -r n; [[ "${n:-1}" == "0" ]] && ok "every faculty-derived lead has evidence" || bad "$n faculty leads have no evidence"; }

psql -d opportunity_agent -tAc "
select count(*) from faculty f
where f.email is not null and f.email_source_url is null
" 2>/dev/null | { read -r n; [[ "${n:-1}" == "0" ]] && ok "every stored email cites a source page" || bad "$n emails have no source URL"; }

psql -d opportunity_agent -tAc "
select count(*) from opportunities where deadline is not null and deadline_confidence = 0
" 2>/dev/null | { read -r n; [[ "${n:-1}" == "0" ]] && ok "no deadline is asserted at zero confidence" || bad "$n deadlines asserted with zero confidence"; }

psql -d opportunity_agent -tAc "
select count(*) from requirements where kind not in ('required','preferred','inferred')
" 2>/dev/null | { read -r n; [[ "${n:-1}" == "0" ]] && ok "requirement kinds are all valid" || bad "$n requirements have a bad kind"; }

# A requirement whose source sentence is itself worded as preferred must never be
# stored as required. Anchored to the qualification sense of the word, so
# "indicate your preferred time commitment" is not a false positive.
psql -d opportunity_agent -tAc "
select count(*) from requirements
where kind = 'required' and source_text ~* '(is |are |strongly )?(preferred|desired|a plus|nice to have)( qualification)?[.,;]?\\s*\$'
" 2>/dev/null | { read -r n; [[ "${n:-1}" == "0" ]] && ok "no preferred qualification stored as required" || bad "$n preferred lines stored as required"; }

head_ "6. Frontend build"
if [[ "${SKIP_BUILD:-0}" == "1" ]]; then
  echo "  (skipped; set SKIP_BUILD=0 to run)"
elif (cd "$WEB" && npm run build >/tmp/trellis-web-build.log 2>&1); then
  ok "next build"
else
  bad "next build — see /tmp/trellis-web-build.log"
fi

printf '\n\033[1mResult: %d passed, %d failed\033[0m\n' "$PASS" "$FAIL"
[[ "${STARTED:-0}" == "1" ]] && echo "(left uvicorn running on :8000)"
exit $(( FAIL > 0 ? 1 : 0 ))
