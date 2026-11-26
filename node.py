"""One sync node. See SPEC.md for the rule and protocol.

python3 node.py --id A --port 7001 --root node-a --peers http://127.0.0.1:7002,http://127.0.0.1:7003
"""
import argparse, datetime, fnmatch, hashlib, json, os, posixpath, threading, time, uuid
import urllib.error, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

NODES = ("A", "B", "C")
IGNORE = (".DS_Store", "*.swp", "*.swx", "*~", ".#*", "~$*", ".~lock.*", "*.tmp", "*.part", "*.crdownload", "4913")
TICK = 1.0


def ignored(name):
    return any(fnmatch.fnmatch(name, p) for p in IGNORE)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def iso(ts=None):
    t = datetime.datetime.fromtimestamp(ts if ts is not None else time.time(), datetime.timezone.utc)
    return t.isoformat(timespec="milliseconds")


def compare(a, b):
    """'eq', 'gt' (a newer), 'lt' (b newer) or 'conc' (made without seeing each other)."""
    ge = all(a.get(n, 0) >= b.get(n, 0) for n in NODES)
    le = all(a.get(n, 0) <= b.get(n, 0) for n in NODES)
    return "eq" if ge and le else "gt" if ge else "lt" if le else "conc"


def later(x, y):
    """The version that keeps the name: later edit time, then later node letter."""
    return x if (x["edited_at"], x["edited_by"]) >= (y["edited_at"], y["edited_by"]) else y


def conflict_name(path, entry):
    d, base = posixpath.split(path)
    stem, ext = os.path.splitext(base)
    return posixpath.join(d, f"{stem}.conflict-{entry['edited_by']}-{entry['fingerprint'][:8]}{ext}")


class Node:
    def __init__(self, me, root, peers):
        self.me, self.peers = me, peers
        self.root = os.path.abspath(root)
        self.shared = os.path.join(self.root, "shared")
        self.tmp = os.path.join(self.root, "tmp")
        self.state_file = os.path.join(self.root, "state.json")
        os.makedirs(self.shared, exist_ok=True)
        os.makedirs(self.tmp, exist_ok=True)
        self.files = {}  # path -> entry (entries are never mutated, only replaced)
        if os.path.exists(self.state_file):
            with open(self.state_file) as f:
                self.files = json.load(f)["files"]
        self.lock = threading.Lock()
        self.prev = {}   # previous scan's observations, for the two-scan stability check
        self.dirty = False
        self.was_offline = None
        self.told = set()  # messages already written, so a clash retried every round is logged once

    # ---------- helpers ----------
    def log(self, msg):
        print(f"[{self.me}] {msg}", flush=True)

    def tell(self, kind, path, msg):
        """How a person is told: a line in node-x/conflicts.log and on stdout. Exact repeats are skipped."""
        if (kind, path, msg) in self.told:
            return
        self.told.add((kind, path, msg))
        line = f"{iso()}  {kind:<13} {path}  {msg}"
        self.log(line)
        with open(os.path.join(self.root, "conflicts.log"), "a") as f:
            f.write(line + "\n")

    def offline(self):
        return os.path.exists(os.path.join(self.root, "OFFLINE"))

    def disk(self, path):
        return os.path.join(self.shared, *path.split("/"))

    def put(self, path, entry):
        with self.lock:
            self.files[path] = entry
        self.dirty = True

    def save(self):
        if not self.dirty:
            return
        with self.lock:
            data = json.dumps({"node": self.me, "files": self.files}, indent=1, sort_keys=True)
        tmp = self.state_file + ".tmp"
        with open(tmp, "w") as f:
            f.write(data)
        os.replace(tmp, self.state_file)
        self.dirty = False

    # ---------- local scanning ----------
    def observe(self, path):
        """What is on disk at path now: (kind, fingerprint, mtime) or None."""
        p = self.disk(path)
        try:
            if os.path.islink(p):
                return None
            if os.path.isdir(p):
                return ("dir", "dir", None)
            with open(p, "rb") as f:
                data = f.read()
            return ("file", sha256(data), os.stat(p).st_mtime)
        except OSError:
            return None

    def walk(self):
        out = {}
        def rec(abs_dir, rel):
            try:
                it = list(os.scandir(abs_dir))
            except OSError:
                return
            for e in it:
                if ignored(e.name) or e.is_symlink():
                    continue
                path = f"{rel}/{e.name}" if rel else e.name
                if e.is_dir():
                    out[path] = ("dir", "dir", None)
                    rec(e.path, path)
                elif e.is_file():
                    out[path] = self.observe(path)
        rec(self.shared, "")
        return {p: o for p, o in out.items() if o}

    def view(self, path):
        """What the state says should be on disk: (kind, fingerprint) or None."""
        e = self.files.get(path)
        return (e["kind"], e["fingerprint"]) if e and e["fingerprint"] is not None else None

    def matches(self, path, obs):
        return (obs[:2] if obs else None) == self.view(path)

    def record_local(self, path, obs):
        old = self.files.get(path)
        card = dict(old["scorecard"]) if old else {n: 0 for n in NODES}
        card[self.me] += 1
        kind = obs[0] if obs else (old["kind"] if old else "file")
        entry = {"scorecard": card, "fingerprint": obs[1] if obs else None, "kind": kind,
                 "edited_at": iso(obs[2]) if obs and obs[2] else iso(), "edited_by": self.me}
        self.put(path, entry)
        self.log(f"local {'delete' if not obs else 'change'}: {path}  {self.card(card)}")

    def scan(self):
        cur = self.walk()
        for path in sorted(set(cur) | {p for p in self.files if self.view(p)}):
            obs = cur.get(path)
            key = obs[:2] if obs else None
            stable = key == (self.prev.get(path)[:2] if self.prev.get(path) else None)
            if stable and not self.matches(path, obs):
                self.record_local(path, obs)
        self.prev = cur

    @staticmethod
    def card(c):
        return " ".join(f"{n}{c.get(n, 0)}" for n in NODES)

    # ---------- disk writes ----------
    def write(self, path, data):
        """Atomic: write into node-x/tmp, then one os.replace into shared/."""
        target = self.disk(path)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        tmp = os.path.join(self.tmp, uuid.uuid4().hex)
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, target)

    def remove_dir(self, path):
        p = self.disk(path)
        try:
            for name in os.listdir(p):          # only ignored junk (e.g. .DS_Store) may remain
                if not ignored(name):
                    return False
            for name in os.listdir(p):
                os.remove(os.path.join(p, name))
            os.rmdir(p)
            return True
        except FileNotFoundError:
            return True
        except OSError:
            return False

    # ---------- network ----------
    def get(self, peer, url_path):
        with urllib.request.urlopen(peer + url_path, timeout=2) as r:
            return r.read()

    def fetch(self, peer, path, fingerprint):
        """Bytes of path from peer, or None if unavailable or not the expected version."""
        try:
            data = self.get(peer, "/file?path=" + urllib.parse.quote(path))
        except (OSError, urllib.error.URLError):
            return None
        return data if sha256(data) == fingerprint else None

    def local_bytes(self, path, fingerprint):
        try:
            with open(self.disk(path), "rb") as f:
                data = f.read()
        except OSError:
            return None
        return data if sha256(data) == fingerprint else None

    # ---------- sync ----------
    def pull(self, peer):
        try:
            remote = json.loads(self.get(peer, "/index"))["files"]
        except (OSError, ValueError, KeyError, urllib.error.URLError):
            return  # peer offline or unreachable: try again next round
        later = []
        for path in sorted(remote):
            if self.offline():
                return
            r = remote[path]
            if (r["kind"] == "dir" and r["fingerprint"] is None) or \
               (r["kind"] == "file" and os.path.isdir(self.disk(path))):
                later.append(path)  # removes a local folder: do it after the folder's contents
                continue
            self.apply(peer, path, r)
        for path in reversed(later):
            if self.offline():
                return
            self.apply(peer, path, remote[path])

    def apply(self, peer, path, r):
        l = self.files.get(path)
        if not self.matches(path, self.observe(path)):
            return  # local edit not scanned yet; the scanner records it first (guard)
        rel = compare(r["scorecard"], l["scorecard"]) if l else "gt"
        if rel == "gt":
            self.adopt(peer, path, r)
        elif rel == "conc":
            self.resolve(peer, path, l, r)

    def materialize(self, peer, path, e):
        """Make the disk match entry e. True on success.

        Callers have checked that the disk matches the stored entry, and e is newer than it, replaces a
        delete, or won a clash whose loser was saved as a copy. So whatever is at the path may be
        replaced, even a file by a folder or an emptied folder by a file."""
        p = self.disk(path)
        try:
            if e["fingerprint"] is None:
                if e["kind"] == "dir":
                    return self.remove_dir(path)
                if os.path.lexists(p):
                    os.remove(p)
                return True
            if e["kind"] == "dir":
                if os.path.isfile(p):
                    os.remove(p)  # the file was replaced by a folder of the same name
                os.makedirs(p, exist_ok=True)
                return True
            data = self.local_bytes(path, e["fingerprint"]) or self.fetch(peer, path, e["fingerprint"])
            if data is None:
                return False
            if os.path.isdir(p) and not self.remove_dir(path):
                self.tell("PATH-CLASH", path, f"version from {e['edited_by']} is a file, but the folder here "
                                              f"still holds files; rename one")
                return False
            self.write(path, data)
            return True
        except OSError as ex:  # e.g. a file where a folder should be
            self.tell("PATH-CLASH", path, f"cannot apply version from {e['edited_by']}: {ex}; skipped")
            return False

    def adopt(self, peer, path, r):
        if self.materialize(peer, path, r):
            self.put(path, dict(r))

    def resolve(self, peer, path, l, r):
        merged = {n: max(l["scorecard"].get(n, 0), r["scorecard"].get(n, 0)) for n in NODES}
        lf, rf = l["fingerprint"], r["fingerprint"]
        if lf == rf:  # same outcome reached independently
            self.put(path, dict(later(l, r), scorecard=merged))
        elif lf is None or rf is None:  # delete vs edit: the edit wins
            live, dead = (r, l) if lf is None else (l, r)
            if live is r and not self.materialize(peer, path, r):
                return
            self.put(path, dict(live, scorecard=merged))
            if live["kind"] == "file":
                self.tell("DELETE-UNDONE", path, f"delete on {dead['edited_by']} overridden by a concurrent edit on {live['edited_by']}; file kept")
        elif l["kind"] != r["kind"]:
            self.tell("PATH-CLASH", path, f"file on one node, folder on another ({l['edited_by']} vs {r['edited_by']}); rename one")
        else:  # two different edits: later one keeps the name, other becomes a conflict copy
            win = later(l, r)
            lose = r if win is l else l
            copy = conflict_name(path, lose)
            if self.view(copy) != ("file", lose["fingerprint"]):
                data = (self.local_bytes(path, lf) if lose is l else self.fetch(peer, path, rf))
                if data is None:
                    return
                if not self.matches(copy, self.observe(copy)):
                    return
                self.write(copy, data)
                self.record_local(copy, self.observe(copy))
            if win is r and not self.materialize(peer, path, r):
                return
            self.put(path, dict(win, scorecard=merged))
            self.tell("CLASH", path, f"kept {win['edited_by']}'s edit ({win['edited_at']}); "
                                     f"{lose['edited_by']}'s edit saved as {copy}")

    # ---------- main loop ----------
    def run(self):
        while True:
            off = self.offline()
            if off != self.was_offline:
                self.log("OFFLINE marker found: not sending or accepting anything" if off
                         else "online: syncing with peers")
                self.was_offline = off
            try:
                self.scan()  # keeps running while offline, so offline edits are recorded
                if not off:
                    for peer in self.peers:
                        if self.offline():
                            break
                        self.pull(peer)
                self.save()
            except Exception as ex:  # keep the node alive; the next round retries
                self.log(f"error in round: {ex!r}")
            time.sleep(TICK)


def serve(node, port):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def reply(self, code, body=b"", ctype="application/octet-stream"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if node.offline():
                return self.reply(503, b"offline")
            u = urllib.parse.urlparse(self.path)
            if u.path == "/index":
                with node.lock:
                    body = json.dumps({"node": node.me, "files": node.files}).encode()
                return self.reply(200, body, "application/json")
            if u.path == "/file":
                path = urllib.parse.parse_qs(u.query).get("path", [""])[0]
                if not path or ".." in path.split("/") or path.startswith("/"):
                    return self.reply(400)
                try:
                    with open(node.disk(path), "rb") as f:
                        return self.reply(200, f.read())
                except OSError:
                    return self.reply(404)
            self.reply(404)

    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True, choices=NODES)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--root", required=True)
    ap.add_argument("--peers", required=True, help="comma-separated base URLs")
    a = ap.parse_args()
    node = Node(a.id, a.root, [p for p in a.peers.split(",") if p])
    threading.Thread(target=serve, args=(node, a.port), daemon=True).start()
    node.log(f"listening on {a.port}, peers {node.peers}")
    try:
        node.run()
    except KeyboardInterrupt:  # Ctrl-C in the run.py terminal reaches every node
        node.save()
