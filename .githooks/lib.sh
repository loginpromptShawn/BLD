#!/usr/bin/env bash
#
# lib.sh — shared helpers for bld git hooks.
# Hook scripts should `source` this file, not execute it.
#
# Audit logs are written under the repository's git dir (outside the working
# tree) so they are private per-checkout and never committed:
#   <git-dir>/hook-audit.log        # human-readable index of every event
#   <git-dir>/hook-logs/<id>.log    # full output of each individual attempt
#
set -uo pipefail

# --- Resolve paths from the git dir -----------------------------------------
GIT_DIR_PATH="$(git rev-parse --git-dir)"
AUDIT_LOG="${GIT_DIR_PATH}/hook-audit.log"
LOGS_DIR="${GIT_DIR_PATH}/hook-logs"
MAX_ATTEMPT_LOGS=200      # per-attempt full-output logs to keep
MAX_AUDIT_BYTES=5242880   # 5 MB: rotate the audit index when it exceeds this

mkdir -p "$LOGS_DIR"

# --- Audit index helpers ----------------------------------------------------
audit() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S %z')" "$*" >> "$AUDIT_LOG"
}

audit_rule() {
  printf '%s\n' "-----------------------------------------------------------------" >> "$AUDIT_LOG"
}

# Keep the audit index from growing unbounded: rotate to hook-audit.log.1.
rotate_audit() {
  if [ -f "$AUDIT_LOG" ] && [ "$(wc -c < "$AUDIT_LOG")" -gt "$MAX_AUDIT_BYTES" ]; then
    mv "$AUDIT_LOG" "${AUDIT_LOG}.1" 2>/dev/null || true
  fi
}

# --- Per-attempt full-output log --------------------------------------------
# begin_attempt() creates a fresh full-output log and sets globals:
#   ATTEMPT_ID, ATTEMPT_LOG
begin_attempt() {
  ATTEMPT_ID="$(date '+%Y%m%d-%H%M%S')-$$"
  ATTEMPT_LOG="${LOGS_DIR}/${ATTEMPT_ID}.log"
  : > "$ATTEMPT_LOG"
  rotate_audit
  prune_attempt_logs
}

# Keep only the newest MAX_ATTEMPT_LOGS per-attempt logs.
prune_attempt_logs() {
  local count oldest
  count="$(find "$LOGS_DIR" -maxdepth 1 -name '*.log' | wc -l | tr -d ' ')"
  while [ "$count" -gt "$MAX_ATTEMPT_LOGS" ]; do
    oldest="$(find "$LOGS_DIR" -maxdepth 1 -name '*.log' -print0 | xargs -0 ls -t | tail -n 1)"
    rm -f "$oldest"
    count=$((count - 1))
  done
}
