# Manual test plan

Run everything from the repo root. **Terminal 1** runs the nodes. **Terminal 2** runs the tests.

## Setup (paste into terminal 2 once)

```bash
same() { diff -r -x .DS_Store node-a/shared node-b/shared && diff -r -x .DS_Store node-a/shared node-c/shared && echo "ALL THREE MATCH"; }
ab()   { diff -r -x .DS_Store node-a/shared node-b/shared && echo "A and B MATCH"; }
off()  { touch node-$1/OFFLINE; }          # off b   → B offline
on()   { rm -f node-$1/OFFLINE; }          # on b    → B back
w()    { sleep 6; }                        # wait for ~2 sync rounds
logs() { tail -n 5 node-*/conflicts.log 2>/dev/null; }
fp()   { shasum -a 256 "$1" | cut -c1-8; } # first 8 hex of a file's fingerprint
```

**Fresh start before each scenario.** In terminal 1, stop the nodes with Ctrl-C, then run:

```bash
rm -rf node-a node-b node-c && python3 run.py
```

`same` must print **ALL THREE MATCH** at the end of every scenario.

---

## T1 Basic add, edit, delete (all online)
```bash
echo v1 > node-a/shared/plan.txt; w; cat node-b/shared/plan.txt node-c/shared/plan.txt   # v1 v1
echo v2 > node-b/shared/plan.txt; w; cat node-a/shared/plan.txt                          # v2
rm node-c/shared/plan.txt; w; ls node-a/shared node-b/shared                             # plan.txt gone
same
```
**Look for:** no conflict copies, and nothing in `logs`.

## T2 Offline catch-up in both directions
```bash
off b
echo fromA > node-a/shared/a.txt
echo fromB > node-b/shared/b.txt
w; ls node-b/shared                 # only b.txt: B heard nothing
on b; w; same                       # a.txt and b.txt on all three
```

## T3 Concurrent edits to the same file on two offline nodes ★
```bash
echo draft > node-a/shared/report.txt; w
off a; off b
echo "A's text" > node-a/shared/report.txt
sleep 2
echo "B's text" > node-b/shared/report.txt
on a; on b; w
ls node-a/shared                     # report.txt + report.conflict-A-xxxxxxxx.txt
cat node-c/shared/report.txt         # B's text (later edit keeps the name)
cat node-c/shared/report.conflict-A-*.txt   # A's text
fp node-a/shared/report.conflict-A-*.txt    # matches the xxxxxxxx in the name
logs; same
```
**Strong result:** both texts survive, the same two files are on all three nodes, and one CLASH line is logged.

## T4 Delete while another node is away (no resurrection) ★
```bash
echo notes > node-a/shared/old.txt; w
off c
rm node-a/shared/old.txt; w
on c; w
ls node-*/shared | grep old.txt || echo "stays deleted"
same
```

## T5 Delete on one node while another edits offline ★
```bash
echo v1 > node-a/shared/budget.txt; w
off c
echo "C's edit" > node-c/shared/budget.txt
rm node-a/shared/budget.txt; w
on c; w
cat node-a/shared/budget.txt          # C's edit (the edit beats the delete)
logs                                  # DELETE-UNDONE line
same
```

## T6 One node offline the whole time
```bash
off c
echo 1 > node-a/shared/x.txt; echo 2 > node-b/shared/y.txt; w
echo 1b > node-b/shared/x.txt; rm node-a/shared/y.txt; w
ab                                    # A and B match while C stays offline
ls node-c/shared                      # unchanged
on c; w; same                         # optional: C converges when it returns
```
**Look for:** A and B keep syncing every ~2 s. The terminal 1 output shows no stalls or tracebacks from C refusing requests.

## T7 Rapid edits and slow writes
```bash
for i in $(seq 1 50); do echo $i > node-a/shared/rapid.txt; sleep 0.05; done; w
cat node-b/shared/rapid.txt            # 50
(for i in $(seq 1 20); do echo line$i; sleep 0.2; done) > node-a/shared/slow.txt; w
wc -l node-*/shared/slow.txt           # 20 on every node
ls node-*/shared                       # no temp or partial files anywhere
same
```

## T8 Reconnect in different orders
```bash
echo base > node-a/shared/r.txt; w
off b; off c
echo B1 > node-b/shared/r.txt; echo onlyB > node-b/shared/b.txt
sleep 1
echo C1 > node-c/shared/r.txt; echo onlyC > node-c/shared/c.txt
on c; w; on b; w; same; ls node-a/shared
```
Then repeat from a fresh start with `on b` before `on c`. **Look for:** the same final file set in both orders: `r.txt` = C1, plus `r.conflict-B-…`, `b.txt` and `c.txt`.

## T9 Relay through a third node
```bash
echo v1 > node-a/shared/x.txt; w
off c; echo v2 > node-a/shared/x.txt; w
off a; on c; w; cat node-c/shared/x.txt   # v2, received through B
on a; w; same
```

## T10 Same content created on two nodes
```bash
off b; echo hi > node-a/shared/hello.txt; echo hi > node-b/shared/hello.txt
on b; w; ls node-a/shared                  # only hello.txt, no conflict copy
```

## T11 Re-create a deleted file
```bash
echo old > node-a/shared/n.txt; w; rm node-a/shared/n.txt; w
echo new > node-b/shared/n.txt; w; cat node-a/shared/n.txt   # new
```

## T12 Rename while another node edits the old name
```bash
echo v1 > node-a/shared/doc.txt; w
off b; mv node-a/shared/doc.txt node-a/shared/doc2.txt; echo "B edit" > node-b/shared/doc.txt
on b; w; ls node-a/shared                  # doc.txt (B edit) and doc2.txt (v1)
same
```

## T13 Folders: nested, empty, deleted
```bash
mkdir -p node-a/shared/proj/src node-a/shared/empty; echo x > node-a/shared/proj/src/m.py; w
ls -R node-c/shared                        # proj/src/m.py and empty/
rm -r node-b/shared/proj; w; same
```

## T14 OFFLINE really means "accepts nothing"
```bash
off b
curl -s -o /dev/null -w "%{http_code}\n" localhost:7002/index   # 503
on b; sleep 3
curl -s -o /dev/null -w "%{http_code}\n" localhost:7002/index   # 200
```

## T15 OFFLINE flapping during edits
```bash
for i in $(seq 1 10); do off b; echo a$i > node-a/shared/f.txt; sleep 0.7; on b; sleep 0.7; done; w; same
```

## T16 Three-way concurrent edit
```bash
echo base > node-a/shared/t.txt; w
off a; off b; off c
echo A > node-a/shared/t.txt; sleep 1; echo B > node-b/shared/t.txt; sleep 1; echo C > node-c/shared/t.txt
on b; w; on a; w; on c; w
ls node-a/shared   # t.txt (C) + t.conflict-A-… + t.conflict-B-…
same
```

## T17 Binary file
```bash
head -c 200000 /dev/urandom > node-a/shared/blob.bin; w
shasum -a 256 node-*/shared/blob.bin       # three identical hashes
```

---

## Final convergence check (after a messy session)
```bash
on a; on b; on c; sleep 10
same
python3 compare.py      # prints per-file fingerprints for all 3 nodes and MATCH / DIFFER
```

The automated version of T1–T17 will be `tests/scenarios.sh`. It runs each scenario from a fresh start and stops at the first failure.
