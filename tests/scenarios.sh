#!/usr/bin/env bash
# Automated scenarios. Each test names the SPEC requirement it proves.
# Usage (from anywhere; stop any running `python3 run.py` first, the tests use ports 7001-7003):
#   tests/scenarios.sh            # run all
#   tests/scenarios.sh t3 t5      # run some
# Each test starts from empty folders. Node output goes to test-run.log.
set -u
cd "$(dirname "$0")/.."
W=${W:-5}                 # seconds to wait for sync
PASS=0; FAIL=0; FAILS=""; NODES_PID=""; FAILED=0; CUR=""

stop()  { if [ -n "$NODES_PID" ]; then kill "$NODES_PID" 2>/dev/null; wait "$NODES_PID" 2>/dev/null; NODES_PID=""; fi; }
start() { stop; rm -rf node-a node-b node-c; python3 run.py >> test-run.log 2>&1 & NODES_PID=$!; sleep 2; }
trap stop EXIT
w()   { sleep "$W"; }
off() { touch "node-$1/OFFLINE"; }
on()  { rm -f "node-$1/OFFLINE"; }

# assertions
check()   { local d=$1; shift; if "$@"; then echo "   ok    $d"; else echo "   FAIL  $d"; FAILED=1; fi; }
same()    { python3 compare.py --quiet; }
pair()    { python3 compare.py --quiet "$1" "$2"; }
has()     { [ "$(cat "$1" 2>/dev/null)" = "$2" ]; }
absent()  { [ ! -e "$1" ]; }
count()   { local n; n=$(ls -d $1 2>/dev/null | wc -l | tr -d ' '); [ "$n" = "$2" ]; }   # $1 is a glob
logged()  { grep -q "$1" node-*/conflicts.log 2>/dev/null; }
fp8()     { python3 -c 'import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest()[:8])' "$1"; }
http()    { curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$1/index"; }

begin() { CUR=$1; FAILED=0; echo "$1  $2"; echo "===== $1 =====" >> test-run.log; start; }
end()   { stop; if [ "$FAILED" = 0 ]; then PASS=$((PASS+1)); else FAIL=$((FAIL+1)); FAILS="$FAILS $CUR"; fi; }

t1() { begin T1 "basic add, edit, delete [R1]"
  echo v1 > node-a/shared/plan.txt; w
  check "B and C got plan.txt"   eval 'has node-b/shared/plan.txt v1 && has node-c/shared/plan.txt v1'
  echo v2 > node-b/shared/plan.txt; w
  check "edit reached A"         has node-a/shared/plan.txt v2
  rm node-c/shared/plan.txt; w
  check "delete reached A and B" eval 'absent node-a/shared/plan.txt && absent node-b/shared/plan.txt'
  check "no conflicts"           eval '! logged CLASH'
  check "all three match"        same
  end; }

t2() { begin T2 "offline catch-up, both directions [R2, R7]"
  off b; echo fromA > node-a/shared/a.txt; echo fromB > node-b/shared/b.txt; w
  check "offline B heard nothing" absent node-b/shared/a.txt
  check "A heard nothing from B"  absent node-a/shared/b.txt
  on b; w
  check "B caught up"             has node-b/shared/a.txt fromA
  check "A and C got B's file"    eval 'has node-a/shared/b.txt fromB && has node-c/shared/b.txt fromB'
  check "all three match"         same
  end; }

t3() { begin T3 "concurrent edits on two offline nodes [R3, R11]"
  echo draft > node-a/shared/report.txt; w
  off a; off b
  echo "A's text" > node-a/shared/report.txt; sleep 2
  echo "B's text" > node-b/shared/report.txt; sleep 2
  on a; on b; w
  local f; f=$(ls node-a/shared/report.conflict-A-*.txt 2>/dev/null | head -1)
  check "later edit (B) keeps the name"   eval 'has node-a/shared/report.txt "B'"'"'s text" && has node-c/shared/report.txt "B'"'"'s text"'
  check "one conflict copy on each node"  eval 'count "node-a/shared/report.conflict-*" 1 && count "node-b/shared/report.conflict-*" 1 && count "node-c/shared/report.conflict-*" 1'
  check "copy holds A's text"             has "$f" "A's text"
  check "copy name = loser + fingerprint" eval '[ -n "$f" ] && [ "$f" = "node-a/shared/report.conflict-A-$(fp8 "$f").txt" ]'
  check "CLASH logged"                    logged CLASH
  check "all three match"                 same
  end; }

t4() { begin T4 "delete while another node is away [R4]"
  echo notes > node-a/shared/old.txt; w
  off c; rm node-a/shared/old.txt; w
  on c; w
  check "stays deleted everywhere" eval 'absent node-a/shared/old.txt && absent node-b/shared/old.txt && absent node-c/shared/old.txt'
  check "all three match"          same
  end; }

t5() { begin T5 "delete vs offline edit [R3, R4]"
  echo v1 > node-a/shared/budget.txt; w
  off c; echo "C's edit" > node-c/shared/budget.txt
  rm node-a/shared/budget.txt; w
  on c; w
  check "edit wins over delete" eval 'has node-a/shared/budget.txt "C'"'"'s edit" && has node-b/shared/budget.txt "C'"'"'s edit"'
  check "DELETE-UNDONE logged"  logged DELETE-UNDONE
  check "all three match"       same
  end; }

t6() { begin T6 "one node offline throughout [R6]"
  off c
  echo 1 > node-a/shared/x.txt; echo 2 > node-b/shared/y.txt; w
  echo 1b > node-b/shared/x.txt; rm node-a/shared/y.txt; w
  check "A and B in sync"     eval 'has node-a/shared/x.txt 1b && absent node-b/shared/y.txt && pair a b'
  check "C untouched"         eval 'absent node-c/shared/x.txt'
  on c; w
  check "C converges later"   same
  end; }

t7() { begin T7 "rapid edits and slow writes [R12]"
  for i in $(seq 1 50); do echo "$i" > node-a/shared/rapid.txt; sleep 0.05; done; w
  check "last rapid value synced" eval 'has node-b/shared/rapid.txt 50 && has node-c/shared/rapid.txt 50'
  (for i in $(seq 1 20); do echo "line$i"; sleep 0.2; done) > node-a/shared/slow.txt; w
  check "slow file complete on B" eval '[ "$(wc -l < node-b/shared/slow.txt)" -eq 20 ]'
  check "no conflicts"            eval '! logged CLASH'
  check "all three match"         same
  end; }

t8_common() {
  echo base > node-a/shared/r.txt; w
  off b; off c
  echo B1 > node-b/shared/r.txt; echo onlyB > node-b/shared/b.txt; sleep 1.5
  echo C1 > node-c/shared/r.txt; echo onlyC > node-c/shared/c.txt; sleep 2
}
t8_checks() {
  check "r.txt = C1 (later edit)" eval 'has node-a/shared/r.txt C1 && has node-b/shared/r.txt C1'
  check "one copy of B's edit"    eval 'count "node-a/shared/r.conflict-B-*" 1 && count "node-a/shared/r.conflict-*" 1'
  check "b.txt and c.txt present" eval 'has node-a/shared/b.txt onlyB && has node-a/shared/c.txt onlyC'
  check "all three match"         same
}
t8() { begin T8a "reconnect order: C then B [R2, R5, R11]"
  t8_common; on c; w; on b; w; t8_checks; end
  begin T8b "reconnect order: B then C [R2, R5, R11]"
  t8_common; on b; w; on c; w; t8_checks; end; }

t9() { begin T9 "change relayed through a third node [R2]"
  echo v1 > node-a/shared/x.txt; w
  off c; echo v2 > node-a/shared/x.txt; w
  off a; on c; w
  check "C got v2 through B" has node-c/shared/x.txt v2
  on a; w
  check "all three match"    same
  end; }

t10() { begin T10 "same content made on two nodes [R11]"
  off b; echo hi > node-a/shared/hello.txt; echo hi > node-b/shared/hello.txt; sleep 2
  on b; w
  check "no conflict copy" eval 'count "node-a/shared/hello*" 1'
  check "all three match"  same
  end; }

t11() { begin T11 "re-create a deleted file [R1, R4]"
  echo old > node-a/shared/n.txt; w; rm node-a/shared/n.txt; w
  echo new > node-b/shared/n.txt; w
  check "new file everywhere" eval 'has node-a/shared/n.txt new && has node-c/shared/n.txt new'
  check "all three match"     same
  end; }

t12() { begin T12 "rename while another node edits the old name [R3]"
  echo v1 > node-a/shared/doc.txt; w
  off b; mv node-a/shared/doc.txt node-a/shared/doc2.txt; echo "B edit" > node-b/shared/doc.txt; sleep 2
  on b; w
  check "both names survive" eval 'has node-a/shared/doc.txt "B edit" && has node-a/shared/doc2.txt v1'
  check "all three match"    same
  end; }

t13() { begin T13 "nested, empty and deleted folders [R1, R5]"
  mkdir -p node-a/shared/proj/src node-a/shared/empty; echo x > node-a/shared/proj/src/m.py; w
  check "nested file and empty folder on C" eval 'has node-c/shared/proj/src/m.py x && [ -d node-c/shared/empty ]'
  rm -r node-b/shared/proj; w
  check "folder delete reached A and C"     eval 'absent node-a/shared/proj && absent node-c/shared/proj'
  check "all three match"                   same
  end; }

t14() { begin T14 "OFFLINE refuses requests [R7]"
  off b; sleep 1
  check "503 while offline"  eval '[ "$(http 7002)" = 503 ]'
  on b; sleep 1
  check "200 when back"      eval '[ "$(http 7002)" = 200 ]'
  end; }

t15() { begin T15 "OFFLINE flapping during edits [R2, R7]"
  for i in $(seq 1 10); do off b; echo "a$i" > node-a/shared/f.txt; sleep 0.7; on b; sleep 0.7; done; w
  check "B has the last value" has node-b/shared/f.txt a10
  check "all three match"      same
  end; }

t16() { begin T16 "three-way concurrent edit [R3, R11]"
  echo base > node-a/shared/t.txt; w
  off a; off b; off c
  echo A > node-a/shared/t.txt; sleep 1; echo B > node-b/shared/t.txt; sleep 1; echo C > node-c/shared/t.txt; sleep 2
  on b; w; on a; w; on c; w
  check "C (latest) keeps the name" has node-a/shared/t.txt C
  check "copies of A and B"         eval 'count "node-a/shared/t.conflict-A-*" 1 && count "node-a/shared/t.conflict-B-*" 1'
  check "all three match"           same
  end; }

t17() { begin T17 "binary file [R10]"
  head -c 200000 /dev/urandom > node-a/shared/blob.bin; w
  check "identical bytes everywhere" same
  end; }

: > test-run.log
TESTS=${*:-"t1 t2 t3 t4 t5 t6 t7 t8 t9 t10 t11 t12 t13 t14 t15 t16 t17"}
for t in $TESTS; do "$t"; done
echo; echo "passed: $PASS  failed: $FAIL${FAILS:+  ($FAILS )}"
[ "$FAIL" = 0 ]
