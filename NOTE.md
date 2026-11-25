# Folder sync without a server: design note
Vipul Mahajan · exact rule in `SPEC.md` · tests in `tests/scenarios.sh`

Each node scans its folder every second and pulls every peer's file index. Each file version carries **counters `[A,B,C]`** (a version vector) and a **fingerprint** (SHA-256, or *deleted*). A node adds 1 to its own counter when it detects a local save or delete. Received versions keep their counters.

**1. The rule when nodes hold different versions X and Y of a file**
1. If X's counters are ≥ Y's in every position, **X wins** (its author had seen Y). Deletes included.
2. Otherwise they were made independently. Same fingerprint: nothing to do. One deleted: **keep the content.** Different contents: the later edit time (modification time where saved; tie → later node letter) keeps the name, and the other is saved as `name.conflict-<node>-<fingerprint[:8]>.ext`.
3. The result takes the **maximum of each counter**, with nothing added, so every node reaches the same result on its own.

*Example:* A `[2,0,0]` saved 10:05, B (offline) `[1,1,0]` saved 10:07. `report.txt` keeps B's text with `[2,1,0]`, and A's text goes to `report.conflict-A-f83ed89e.txt`.

**2. What it can't resolve, and what it does.** Each case below writes a line to `node-x/conflicts.log`.
- **Two concurrent edits** (text or binary) are never merged. Both are kept (`CLASH`) and a person picks.
- **Delete vs. concurrent edit:** the edit is kept (`DELETE-UNDONE`) and must be deleted again.
- **Rename vs. edit of the old name:** a rename is a delete plus an add, so both names survive.
- **File here, folder with the same name there:** the path is skipped (`PATH-CLASH`) until someone renames one.

**3. Assumptions.**
- **Machines:** `shared/` and `node-x/` bookkeeping share a local disk, so renames are atomic. There are three fixed nodes. Clocks are roughly right; a wrong one only changes which version keeps the name, never whether it is kept.
- **Network:** any request may fail. Rounds are idempotent and repeat every second, so no delivery or ordering guarantees are needed. Peers are trusted.
- **People:** they save with normal apps. A change counts after two identical scans, so half-written files aren't sent. Temp files have common names. People check the folder or log for conflicts. Nobody saves in the milliseconds between the final check and the replace. Nodes go offline via `OFFLINE`, not by being killed.

**4. Not handled, and why.**
- **Merging:** needs format knowledge; a copy is always safe.
- **Clearing delete records:** only safe once all nodes have seen them, and a node may stay offline forever. They cost bytes.
- **Rename detection:** delete + add is correct, just less tidy.
- **The millisecond race:** closing it needs OS file locks.
- **Optional per the brief:** speed, security, discovery, more than three nodes, crash survival.
- **Outside "same content":** permissions, timestamps and symlinks; also case-only name differences on macOS.
- **`.DS_Store` and editor temp files are never synced;** `compare.py` skips them.
