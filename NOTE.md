# Folder sync without a server: design note

Vipul Mahajan · precise version in `SPEC.md` · tests in `tests/scenarios.sh`

**Design.** Every second, each node scans its folder and pulls the full file index from each peer it can reach. Each file version carries one change counter per node (a version vector). The counters show whether a version was made with knowledge of another, or independently of it.

## 1. When nodes disagree, which content wins?

Every version of a path has:
- **counters `[A,B,C]`.** A node adds 1 to its own counter when it detects a local save or delete. Received versions keep their counters unchanged.
- **a fingerprint**: the SHA-256 of the bytes, or *deleted*.

To decide between versions X and Y of one path:

1. **If X's counters are ≥ Y's in every position, X wins** (its author had seen Y). This includes deletes.
2. **Otherwise the two are concurrent:**
   - (a) Same fingerprint: nothing to decide.
   - (b) One is deleted and one has content: **keep the content.**
   - (c) Two different contents: the version with the later edit time keeps the name. The edit time is the file's modification time on the node where it was saved; a tie goes to the later node letter. The other version is written to `name.conflict-<node>-<first 8 hex of its fingerprint>.ext`.
3. **The result takes the maximum of each counter, with nothing added.** So every node reaches the same result on its own, including the copy's name.

*Example.* A has `[2,0,0]`, saved 10:05. B was offline and has `[1,1,0]`, saved 10:07. Neither is ≥ the other in every position, so they are concurrent. B's text stays in `report.txt` with counters `[2,1,0]`, and A's text goes to `report.conflict-A-f83ed89e.txt`.

## 2. What it can't resolve on its own, and what it does then

- **Two different concurrent edits** (text or binary). Nothing is merged. Both are kept as above, and a `CLASH` line is written to `node-x/conflicts.log` and the console. A person picks.
- **A delete concurrent with an edit.** The edit is kept and `DELETE-UNDONE` is logged. The person who deleted must delete again.
- **A rename concurrent with an edit to the old name.** A rename is a delete plus an add, so both names survive.
- **A file on one node and a folder with the same name on another.** `PATH-CLASH` is logged and that path is skipped until someone renames one. Everything else keeps syncing.

## 3. Assumptions

- **Machines.** Each node's `shared/` and its bookkeeping (`node-x/`) are on the same local disk, so the final rename is atomic. The three node names are fixed. Clocks are roughly right; a wrong clock only changes which concurrent version keeps the name, never whether one is kept.
- **Network.** Any request may fail or time out. Each round is idempotent and repeats every second, so delivery and ordering guarantees aren't needed. Peers are trusted.
- **People.**
  - They save with normal applications. A change counts only once the file looks the same on two scans in a row, so slow writes aren't sent half-finished.
  - Editor temp and lock files follow common names and are ignored.
  - People look in the folder or the log for conflict copies.
  - Nobody saves a file in the few milliseconds between the final check and the replace.
- **Process.** Nodes go offline by the `OFFLINE` file, not by being killed. State is saved after each round but isn't crash-proof.

## 4. What I chose not to handle, and why

- **Merging contents.** It needs knowledge of each format, while a conflict copy is always safe.
- **Clearing delete records (tombstones).** That's only safe once every node has seen the delete, and a node may stay offline forever. Each one costs a few bytes.
- **Detecting renames.** Treating a rename as delete + add is correct, just less tidy.
- **The millisecond race above.** Closing it needs OS file locks.
- **Things the brief made optional:** speed (every file is hashed on every scan and whole files are sent), security, discovery, more than three nodes, and surviving a kill.
- **Things outside "same content":** permissions, timestamps and symlinks.
- **macOS edge cases:** names differing only by case, and Unicode normalization.
- **`.DS_Store` and editor temp files** are never synced, so compare folders with `python3 compare.py`, which excludes them.
