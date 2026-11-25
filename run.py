"""Start nodes A, B and C on ports 7001-7003. Ctrl-C stops all three.

    python3 run.py
"""
import os, signal, subprocess, sys

NODES = {"A": 7001, "B": 7002, "C": 7003}
here = os.path.dirname(os.path.abspath(__file__))

procs = []
for name, port in NODES.items():
    root = os.path.join(here, f"node-{name.lower()}")
    os.makedirs(os.path.join(root, "shared"), exist_ok=True)
    peers = ",".join(f"http://127.0.0.1:{p}" for n, p in NODES.items() if n != name)
    procs.append(subprocess.Popen([sys.executable, "-u", os.path.join(here, "node.py"),
                                   "--id", name, "--port", str(port), "--root", root, "--peers", peers]))


def stop(*_):
    for p in procs:
        p.terminate()  # main loop below then sees the children exit


signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
print("Nodes running: node-a/shared, node-b/shared, node-c/shared. Offline: touch node-x/OFFLINE. Ctrl-C to stop.", flush=True)
for p in procs:
    p.wait()
for p in procs:  # one node died on its own: stop the rest too
    p.terminate()
