# folder-sync

Keeps `node-a/shared`, `node-b/shared` and `node-c/shared` the same without a server. Python 3 standard library only.

```bash
python3 run.py                 # starts A, B and C on ports 7001, 7002 and 7003 (Ctrl-C stops all)
touch node-b/OFFLINE           # B goes offline (keeps running, edits still recorded)
rm node-b/OFFLINE              # B comes back and catches up in both directions
python3 compare.py             # 3-way folder compare: MATCH / DIFFER
tests/scenarios.sh             # 18 automated scenarios (about 8 minutes). Stop run.py first, as they use the same ports
```

- `NOTE.md`: the one-page answers to the four questions.
- `SPEC.md`: requirements, the conflict rule, the protocol and the state format.
- `TEST_PLAN.md`: the same scenarios as copy-paste commands to run by hand.

Clashes are written to `node-x/conflicts.log`. Bookkeeping (`state.json`, `tmp/`, `conflicts.log`, `OFFLINE`) lives in `node-x/`, never inside `shared/`.
