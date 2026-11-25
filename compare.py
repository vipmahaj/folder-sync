"""Compare the shared folders (paths and bytes, ignored names excluded).

    python3 compare.py            # all three, prints a table
    python3 compare.py a b        # just two
    python3 compare.py --quiet    # only MATCH / DIFFER; exit code 0 if they match
"""
import hashlib, os, sys
from node import ignored

here = os.path.dirname(os.path.abspath(__file__))
args = [a for a in sys.argv[1:] if not a.startswith("-")]
quiet = "--quiet" in sys.argv
nodes = [n.lower() for n in args] or ["a", "b", "c"]


def tree(node):
    root, out = os.path.join(here, f"node-{node}", "shared"), {}
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if not ignored(x)]
        for x in dirs:
            out[os.path.relpath(os.path.join(d, x), root)] = "<folder>"
        for x in files:
            if not ignored(x):
                with open(os.path.join(d, x), "rb") as f:
                    out[os.path.relpath(os.path.join(d, x), root)] = hashlib.sha256(f.read()).hexdigest()[:12]
    return out


trees = {n: tree(n) for n in nodes}
paths = sorted(set().union(*trees.values()))
bad = [p for p in paths if len({trees[n].get(p, "-") for n in nodes}) > 1]
if not quiet:
    print("path".ljust(44) + "".join(f"node-{n}".ljust(14) for n in nodes))
    for p in paths:
        mark = "  <-- differs" if p in bad else ""
        print(p[:43].ljust(44) + "".join(trees[n].get(p, "-").ljust(14) for n in nodes) + mark)
if not quiet or bad:
    print("MATCH" if not bad else f"DIFFER ({len(bad)} paths): " + ", ".join(bad[:5]))
sys.exit(1 if bad else 0)
