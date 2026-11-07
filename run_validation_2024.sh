#!/usr/bin/env bash
# Full-year 2024 nodal validation in ~8-day chunks (a full month needs ~25 GB RAM; a chunk ~6-7 GB).
# Chunks never cross a month boundary: days 1-8, 9-16, 17-24, 25-end. Existing outputs are skipped (resumable).
# Usage: bash run_validation_2024.sh [parallel=2] [threads_per_solve=2]; then python validate_2024.py
set -u
cd "$(dirname "$0")"
PY=${PY:-python}
SOL="${VN_DATA:-data}/networks/solved"
LOG="$SOL/validation_2024_run.log"
export PY SOL LOG THREADS=${2:-2}
one() {
  [ -f "$SOL/vn2024_$1_$2.nc" ] && { echo "skip $1"; return; }
  t0=$(date +%s)
  $PY -W ignore solve_vn.py "$1" "$2" > "$SOL/solve_$1.txt" 2>&1
  echo "$(date +%H:%M) $1..$2 exit $? $(( ($(date +%s)-t0)/60 )) min | $(grep -hE '^status|load shedding' "$SOL/solve_$1.txt" | tr '\n' ' ' | cut -c1-160)" | tee -a "$LOG"
}
export -f one
python3 - <<'PY' | xargs -P "${1:-2}" -L 1 bash -c 'one "$@"' _
import calendar
for m in range(1, 13):
    last = calendar.monthrange(2024, m)[1]
    for a, b in [(1, 8), (9, 16), (17, 24), (25, last)]:
        print(f"2024-{m:02d}-{a:02d} 2024-{m:02d}-{b:02d}")
PY
$PY -W ignore validate_2024.py 2>&1 | tail -20 | tee -a "$LOG"
echo "VALIDATION DONE $(date +%H:%M)" | tee -a "$LOG"
