# SPEC: folder sync without a server

This is the contract the code follows. `NOTE.md` explains the same thing in plain language, and `tests/scenarios.sh` checks it. Each test names the requirement it proves.

## Requirements

| ID | Statement (testable) | Source |
|----|----------------------|--------|
| R1 | With all nodes online, a file created, changed or deleted in one `shared/` appears the same way in the other two within a few seconds. | brief req 1 |
| R2 | When `node-x/OFFLINE` is removed, x receives everything it missed **and** the others receive everything x did while offline. | brief req 2 |
| R3 | A saved content is never lost silently. Either a later version was made by someone who had seen it, or it is kept as a conflict copy **and** a line is written to `conflicts.log`. | brief req 3 |
| R4 | A deleted file does not come back from a node that held an older copy. | brief req 4 |
| R5 | All online and no edits for ~10 s: the three `shared/` trees are identical (paths and bytes; ignored names excluded). | brief req 5 |
| R6 | With one node offline forever, R1–R5 hold between the other two, and nothing waits on the offline node. | brief req 6 |
| R7 | While `node-x/OFFLINE` exists, x sends no request and answers every request with `503` before touching state. The process keeps running and keeps scanning. | brief setup |
| R8 | `shared/` only ever holds user files and conflict copies. All bookkeeping lives in `node-x/`. | brief |
| R9 | `python3 run.py` starts A, B and C on ports 7001, 7002 and 7003. Each is given the other two addresses. | brief setup |
| R10 | Files are opaque bytes. Binary and text are treated the same, and conflicts produce copies, never merges. | brief "not required" |
| R11 | Every node resolves a given conflict to the same result (same entry, same conflict-copy name). | implied by R5 |
| R12 | A file is only counted as changed once it has looked the same on two consecutive scans. A received file appears in one atomic `os.replace`. | implied |

## Data: one entry per relative path, in `node-x/state.json`

```json
"docs/report.txt": {
  "scorecard":   {"A": 2, "B": 1, "C": 0},
  "fingerprint": "sha256 hex" | "dir" | null,
  "kind":        "file" | "dir",
  "edited_at":   "2026-11-25T10:07:12.031+00:00",
  "edited_by":   "B"
}
```
- `fingerprint: null` is a **delete note** (tombstone). It is kept forever.
- A **local change** (detected by the scan) sets the scorecard to the previous scorecard (zeros if the path is new) with 1 added at its own node, and records the new fingerprint, the current time and its own node.
- A **received version** is stored exactly as received.

## The rule: comparing local L with remote R for one path

1. If R ≥ L in every column, **adopt R**. If L ≥ R in every column, do nothing. Adopting replaces whatever L had at the path, including a file replaced by a folder or a folder replaced by a file (the folder is removed after its contents).
2. Otherwise they are concurrent. Let M be the maximum of each column, with no +1.
   - Same fingerprint: keep it, with scorecard M. `edited_at` and `edited_by` come from whichever of the two has the later `(edited_at, edited_by)`.
   - One null and one live: **the live one wins**, with scorecard M. Log `DELETE-UNDONE`.
   - Both live but different: W = the later `(edited_at, edited_by)` and the other is the loser. The path gets W's content with scorecard M. The loser's bytes are written to `<stem>.conflict-<loser.edited_by>-<loser.fingerprint[:8]><ext>` as a local change. Log `CLASH`.
   - One is a file and the other a directory: log `PATH-CLASH` and skip.
3. **Guard:** if the path on disk no longer matches L (an edit not yet scanned), skip this path this round. The scanner records the edit first, and the next round sees the true concurrency.

## Protocol (HTTP, pull only)

| Request | Reply |
|---|---|
| `GET /index` | `200` with JSON `{"node": "A", "files": {path: entry}}` |
| `GET /file?path=<p>` | `200` with the raw bytes of `shared/<p>`, or `404` |
| any request while `OFFLINE` exists | `503` |

Every second, each node scans its folder, then pulls `/index` from each peer (2 s timeout). It fetches the bytes it needs and checks the SHA-256 before writing. A peer that fails is skipped until the next round.

## Files

`node-x/shared/` (user files only) · `node-x/state.json` · `node-x/conflicts.log` · `node-x/tmp/` (download staging, same disk) · `node-x/OFFLINE` (marker, empty).

Ignored names, never synced: `.DS_Store`, `*.swp`, `*.swx`, `*~`, `.#*`, `~$*`, `.~lock.*`, `*.tmp`, `*.part`, `*.crdownload`, `4913`. Symlinks are ignored.
