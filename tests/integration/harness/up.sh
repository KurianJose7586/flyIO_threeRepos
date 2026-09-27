#!/usr/bin/env bash
# Brings the integration stack up, idempotently: anything already healthy is
# left alone, anything down is started. Safe to re-run after a container
# restart, which drops processes and /etc/hosts edits but keeps files.
#
#   tests/integration/harness/up.sh          # start / repair
#   tests/integration/harness/up.sh reset    # also wipe DB rows + stub state
#
# Requires root (binds :80, edits /etc/hosts). Assumes the scraper venv
# (flyio-scraper-service/.venv) and admin node_modules are installed, and
# flyio-admin/.env points at this stack — see ../README.md.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
LOG="${LOG_DIR:-/tmp/flyio-integration}"
mkdir -p "$LOG"

PGDATA="${PGDATA:-/var/lib/postgresql/flyiotest}"
PGPORT="${PGPORT:-5433}"
PGBIN="${PGBIN:-/usr/lib/postgresql/16/bin}"
FIXTURE_HOSTS="en.wikivoyage.org www.holidify.com"
NOPROXY="localhost,127.0.0.1,${FIXTURE_HOSTS// /,}"

up() { curl -s --noproxy '*' -o /dev/null -w '%{http_code}' --max-time 3 "$1" 2>/dev/null; }
wait_for() {  # url name
  for _ in $(seq 1 60); do [ "$(up "$1")" != "000" ] && return 0; sleep 1; done
  echo "  !! $2 did not come up — see $LOG/$2.log"; return 1
}

echo "── /etc/hosts"
for h in $FIXTURE_HOSTS; do
  grep -qE "^127\.0\.0\.1[[:space:]]+$h\$" /etc/hosts || echo "127.0.0.1 $h" >> /etc/hosts
done
echo "   ok"

echo "── postgres :$PGPORT"
if ! pg_isready -h 127.0.0.1 -p "$PGPORT" -q 2>/dev/null; then
  if [ ! -f "$PGDATA/PG_VERSION" ]; then
    su postgres -c "$PGBIN/initdb -D $PGDATA -U flyio --auth=trust" > "$LOG/initdb.log" 2>&1
  fi
  # A container restart kills the server without removing its pid file, and
  # a leftover postmaster.pid makes the next start refuse. Only remove it
  # when no process actually holds that pid.
  if [ -f "$PGDATA/postmaster.pid" ] && ! kill -0 "$(head -1 "$PGDATA/postmaster.pid")" 2>/dev/null; then
    rm -f "$PGDATA/postmaster.pid"
  fi
  # The server runs as `postgres`, which cannot write into $LOG (root-owned),
  # so its log lives beside the data directory it already owns.
  su postgres -c "$PGBIN/pg_ctl -D $PGDATA -o '-p $PGPORT -k /tmp' -l $PGDATA/../flyiotest.log -w start" > /dev/null
fi
if ! pg_isready -h 127.0.0.1 -p "$PGPORT" -q; then
  echo "  !! postgres did not start — see $PGDATA/../flyiotest.log"; exit 1
fi
psql -h 127.0.0.1 -p "$PGPORT" -U flyio -d postgres -tAc \
  "SELECT 1 FROM pg_database WHERE datname='flyio_admin_test'" | grep -q 1 \
  || psql -h 127.0.0.1 -p "$PGPORT" -U flyio -d postgres -qc "CREATE DATABASE flyio_admin_test;"
echo "   ok"

start() {  # name health-url command...
  local name="$1" url="$2"; shift 2
  if [ "$(up "$url")" != "000" ]; then echo "── $name  (already up)"; return; fi
  echo "── $name"
  # cd first, so `&` backgrounds only nohup. Written as `cd && nohup … &`,
  # bash backgrounds the whole && list in a forked subshell that keeps this
  # script's stdout for as long as the service runs — so `up.sh | anything`
  # never finished.
  (
    cd "$ROOT" || exit 1
    NO_PROXY="$NOPROXY" no_proxy="$NOPROXY" nohup "$@" > "$LOG/$name.log" 2>&1 < /dev/null &
  )
  wait_for "$url" "$name" && echo "   ok"
}

start fixture  http://127.0.0.1:80/robots.txt   python3 "$HERE/fixture_server.py"
start stub_llm http://127.0.0.1:8101/v1/health  python3 "$HERE/stub_llm.py"
start scraper  http://127.0.0.1:8099/health \
  env SERVICE_API_KEY=live_test_key SEARCH_PROVIDER=mock PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 \
      ${PLAYWRIGHT_BROWSERS_PATH:+PLAYWRIGHT_BROWSERS_PATH=$PLAYWRIGHT_BROWSERS_PATH} \
      "$ROOT/flyio-scraper-service/.venv/bin/python" "$HERE/run_scraper_fixture.py"
start admin    http://127.0.0.1:3100/api/admin/me \
  bash -c "cd flyio-admin && exec npx ts-node-dev --transpile-only src/app.ts"

if [ "${1:-}" = "reset" ]; then
  echo "── reset"
  psql -h 127.0.0.1 -p "$PGPORT" -U flyio -d flyio_admin_test -qc \
    "TRUNCATE knowledge_base, history, job_events, jobs, prompt_history, request_events RESTART IDENTITY CASCADE;"
  curl -s --noproxy '*' -X POST http://127.0.0.1:8101/__reset > /dev/null
  echo "   ok"
fi
