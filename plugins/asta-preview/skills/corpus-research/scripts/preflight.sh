#!/bin/bash
# preflight.sh — portable environment check for corpus-research threads.
# Run from inside a thread dir (has CLAUDE.md + vault/) or anywhere (skips layout checks).
# Usage: bash preflight.sh [expected-branch]
# Checks: claude CLI · plugin install (venv, asta CLI, skill) · thread layout (if in one) ·
#         S2_API_KEY live validation (incl. the quoted-key 403 trap) · asta auth token ·
#         paper-finder endpoint (auto-detects hosted vs localhost from asta.conf).
# Exit 0 = all pass. Machine-specific invariants belong in a caller wrapper, not here.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AP="$(cd "$SCRIPT_DIR/../../../../.." && pwd)"   # plugin repo root (scripts/ -> corpus-research -> skills -> asta-preview -> plugins -> root)
EXPECT_BRANCH="$1"
FAIL=0
ok(){ echo "  ✅ $1"; }; bad(){ echo "  ❌ $1"; FAIL=1; }; warn(){ echo "  ⚠ $1"; }

echo "— tooling —"
command -v claude >/dev/null && ok "claude on PATH" || bad "claude not found on PATH"

echo "— plugin install @ $AP —"
[ -x "$AP/.venv/bin/asta" ] && ok "asta CLI built (.venv/bin/asta)" || bad "no .venv/bin/asta — run 'make install' in $AP"
[ -f "$AP/plugins/asta-preview/skills/corpus-research/SKILL.md" ] && ok "corpus-research skill present" || bad "skill missing under plugins/asta-preview/"
if [ -n "$EXPECT_BRANCH" ]; then
  BR=$(git -C "$AP" branch --show-current 2>/dev/null)
  [ "$BR" = "$EXPECT_BRANCH" ] && ok "branch $BR" || bad "branch is '$BR' (expected $EXPECT_BRANCH)"
fi

if [ -f CLAUDE.md ] && [ -d vault ]; then
  echo "— thread layout ($(pwd)) —"
  [ -f vault/VAULT-MANIFEST.md ] && ok "vault/VAULT-MANIFEST.md" || bad "vault/VAULT-MANIFEST.md missing"
  [ -f vault/QUESTIONS.log ] && ok "vault/QUESTIONS.log" || bad "vault/QUESTIONS.log missing"
else
  echo "— thread layout — not in a thread dir (no CLAUDE.md+vault/ here); skipping"
fi

echo "— Semantic Scholar —"
if [ -z "$S2_API_KEY" ]; then
  bad "S2_API_KEY not exported in this shell"
else
  case "$S2_API_KEY" in
    \"*|\'*) bad "S2_API_KEY is QUOTED (S2 returns 403) — re-export stripping quotes: | tr -d '\"'" ;;
    *) CODE=$(curl -s -o /dev/null -w "%{http_code}" -m 10 -H "x-api-key: $S2_API_KEY" \
         "https://api.semanticscholar.org/graph/v1/paper/CorpusId:2135897?fields=title" 2>/dev/null)
       [ "$CODE" = "200" ] && ok "S2_API_KEY valid (live 200)" || bad "S2 probe HTTP $CODE (401/403=bad key, 000=network)" ;;
  esac
fi

echo "— asta auth —"
if "$AP/.venv/bin/asta" auth status >/dev/null 2>&1; then
  ok "asta auth token present"
else
  warn "no valid asta auth token — run 'asta auth login' (browser) before first hosted use"
fi

echo "— paper-finder endpoint —"
CONF="$AP/src/asta/utils/asta.conf"
if grep -Eq 'base_url *= *"http://localhost:[0-9]+"' "$CONF" 2>/dev/null; then
  URL=$(grep -Eo 'base_url *= *"http://localhost:[0-9]+"' "$CONF" | grep -Eo 'http://localhost:[0-9]+')
  CODE=$(curl -s -o /dev/null -w "%{http_code}" -m 3 "$URL/" 2>/dev/null)
  [ "$CODE" != "000" ] && ok "LOCAL paper-finder configured and up ($URL, HTTP $CODE)" \
    || bad "asta.conf points at $URL but nothing is listening — start the local server or revert the override"
else
  CODE=$(curl -s -o /dev/null -w "%{http_code}" -m 10 https://asta-gateway.apps.allenai.org/ 2>/dev/null)
  [ "$CODE" != "000" ] && ok "hosted gateway reachable (HTTP $CODE)" || bad "hosted gateway unreachable (network/VPN?)"
fi

echo
[ $FAIL -eq 0 ] && echo "PREFLIGHT: ALL PASS" || echo "PREFLIGHT: FAILURES ABOVE"
exit $FAIL
