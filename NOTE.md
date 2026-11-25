# Folder sync without a server: design note

Vipul Mahajan

**Design in one line.** Each node scans its folder every second. Every 2 s it pulls the full file index from each peer it can reach. Each file version carries one change counter per node (a version vector). Comparing two versions' counters shows whether one was made with knowledge of the other, or whether the two were made independently.

## 1. The rule that decides a file's contents

Every version of a path carries:
- **counters** `[A, B, C]`. A node adds 1 to its own counter each time it detects a local save or delete. When it receives a version, it copies all counters as they are.
- **fingerprint**: the SHA-256 of the bytes, or *deleted*.

To decide between versions X and Y of one path:

1. **If X's counters are ≥ Y's in every position, X wins.** Whoever made X had seen Y. This applies to deletes too.
2. **Otherwise the two are concurrent:**
   - (a) Same fingerprint: keep it.
   - (b) One is *deleted* and one has content: **keep the content.**
   - (c) Different content: the version with the later edit time (recorded by the node that made it; if equal, the later node letter) keeps the name. The other is written to `name.conflict-<node>-<first 8 hex of its fingerprint>.ext`.
3. **The result's counters are the maximum of each position.** Nothing is added. Every node therefore reaches an identical result independently, including the conflict file's name.

*Example:* A holds `report.txt [2,0,0]` edited 10:05. B, which was offline, holds `[1,1,0]` edited 10:07. Neither is ≥ the other in every position, so they are concurrent. B's version keeps `report.txt` with counters `[2,1,0]`. A's version becomes `report.conflict-A-9c41e2b0.txt`.

## 2. What it cannot resolve on its own, and what it does

- **Two different concurrent edits to one file** (text or binary). It does not merge. It keeps both as above and writes a line to `node-x/conflicts.log` and stdout. A person chooses.
- **A delete concurrent with an edit.** The edit is kept and the overridden delete is logged. The person who deleted must delete again.
- **A rename concurrent with an edit to the old name.** A rename is seen as delete + add, so both names survive: the old name with the edit, the new name with the earlier content.
- **The same path is a file on one node and a folder on another.** This is logged and that path is skipped until a person renames one of them. Everything else still syncs.

## 3. Assumptions

- **Machines.** `shared/` and the node's bookkeeping folder are on the same local filesystem, so a rename is atomic. The three node names are fixed and known. Clocks are roughly right. Clock error only changes which concurrent version keeps the original name, never whether a version is kept.
- **Network.** Any request may fail, time out or arrive late. Every round is idempotent and repeats every 2 s, so no delivery or ordering guarantee is needed. Peers are trusted.
- **People.**
  - They save with normal applications. A change is only counted after the file is unchanged for two consecutive scans (about 1–2 s), so a slow write is not synced half-finished.
  - Editor temp and lock files follow common names and are ignored.
  - Users look in the folder or the log to notice conflict copies.
  - Nobody saves a file in the same few milliseconds that a sync replaces it.
- **Process.** Nodes are taken offline with the `OFFLINE` file, not killed. State is saved after each change but is not crash-safe.

## 4. What I chose not to handle, and why

- **Merging contents.** Merging needs knowledge of each format. A conflict copy is always safe and simple to explain.
- **Deleting old tombstones (records of deleted files).** It is only safe once every node has seen the delete, and the brief allows a node to stay offline forever. The cost is a few bytes per deleted path.
- **Rename detection.** Treating a rename as delete + add is correct, just less tidy.
- **The small race between the final re-check of a local file and replacing it.** Closing it needs OS file locks, which are platform-specific.
- **Things not required by the brief:** speed (it hashes every file on every scan, sends the full index each round and transfers whole files), security, discovery, more than three nodes, and surviving a kill.
- **Things not part of "the same content":** permissions, modification times and symlinks.
- **macOS edge cases:** names that differ only in letter case, and Unicode normalization.
- **`.DS_Store` and editor temp files** are never synced, so a folder comparison should exclude them. The repo's `compare.py` does this.
