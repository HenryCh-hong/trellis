#!/usr/bin/env bash
# Builds the text-bearing PDF the audit uploads.
#
# Deliberately a generic fictional student, not the user's real resume: a test
# fixture containing someone's actual name, email and history has no business
# in version control.
set -euo pipefail
OUT="${1:-/tmp/trellis-fixture-resume.pdf}"
TXT="$(mktemp -t trellis-fixture).txt"
cat > "$TXT" <<'EOF'
ALEX RIVERA
alex.rivera@example.edu | github.com/example

EDUCATION
Stanford University - B.S. Computer Science, expected 2028
Relevant Coursework: CS 106B Programming Abstractions, CS 107 Computer Organization,
CS 109 Probability, CS 221 Artificial Intelligence, CS 224N Natural Language Processing

RESEARCH EXPERIENCE
Undergraduate Research Assistant, Stanford HCI Group (2025-2026)
- Built a PyTorch evaluation harness for multimodal LLM agents across 4 benchmark suites
- Ran a 40-participant user study on human-AI collaboration in writing tasks
- Co-authored a workshop paper on agent evaluation methodology

PROJECTS
LLM Tutor (2026)
- Fine-tuned an open model for step-by-step math feedback used by 200 classmates
- Implemented retrieval over a course corpus with citation-grounded answers

TECHNICAL SKILLS
Python, PyTorch, TypeScript, React, SQL, Git, Linux, LaTeX, Docker
EOF
cupsfilter "$TXT" > "$OUT" 2>/dev/null
rm -f "$TXT"
echo "$OUT"
