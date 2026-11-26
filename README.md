# folder-sync

Keeps `node-a/shared`, `node-b/shared` and `node-c/shared` the same without a server. Python 3 standard library only.

## Run it

Run every command from this folder (`folder-sync/`). Nothing to install.

**1. Start the three nodes** in terminal 1 and leave it running:

```bash
python3 run.py
```

This creates `node-a/`, `node-b/` and `node-c/` and starts nodes A, B and C on ports 7001, 7002 and 7003. Ctrl-C stops all three.

**2. Make a change and watch it spread**, in terminal 2:

```bash
echo hello > node-a/shared/hello.txt    # add a file on A
sleep 4; cat node-c/shared/hello.txt    # it is now on C: prints "hello"
python3 compare.py                      # lists every file on all three nodes, ends with MATCH or DIFFER
```

**3. Take a node offline and bring it back:**

```bash
touch node-b/OFFLINE    # B stops syncing. It keeps running and still records edits made in node-b/shared
rm node-b/OFFLINE       # B syncs again: it gets what it missed, and A and C get what B changed
```

## Test it

Stop `run.py` first (Ctrl-C in terminal 1), because the tests start their own nodes on the same ports. Each scenario starts from empty folders, so **the tests delete `node-a/`, `node-b/` and `node-c/`**.

```bash
tests/scenarios.sh          # all 20 automated scenarios, about 8 minutes
tests/scenarios.sh t3 t5    # only the scenarios you name
```

Each check prints `ok` or `FAIL`. The nodes' own output goes to `test-run.log`.

## Documents

- [`NOTE.md`](NOTE.md) (and `NOTE.pdf`, one A4 page): the answers to the four questions.
- [`SPEC.md`](SPEC.md): requirements, the conflict rule, the protocol and the state format.
- [`tests/MANUAL.md`](tests/MANUAL.md): the same scenarios as `tests/scenarios.sh`, as copy-paste commands to run by hand.

Clashes are written to `node-x/conflicts.log`. Bookkeeping (`state.json`, `tmp/`, `conflicts.log`, `OFFLINE`) lives in `node-x/`, never inside `shared/`.
