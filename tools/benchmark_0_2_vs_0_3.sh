#!/bin/bash
# Paths below are those of the build host (/workspace/ram/original = untouched 0.2, /workspace/ram/work = 0.3); adapt before reuse.
# Same host, same scene (offshore demo, 1000 replications, seed 42), 0.2 original vs 0.3 work.
set -e
for i in 1 2 3; do
 for v in original work; do
  rm -rf /tmp/bench_$v
  s=$(date +%s.%N)
  PYTHONPATH=/workspace/ram/$v/src /workspace/ram/venv/bin/python -B -m rammodel.cli --demo /tmp/bench_$v --runs 1000 >/dev/null
  e=$(date +%s.%N)
  echo "$v run$i $(python3 -c "print(round($e - $s, 2))") s"
 done
done
