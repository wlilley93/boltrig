import os, sys, json, socket, time
from pathlib import Path
from boltrig.fleet.infrastructure.cell_privilege import read_privilege_state, per_cell_uid_mode_available
from boltrig.fleet.infrastructure.cell_spawner import SpawnPolicy, serve_spawner, receive_spawn_result

print("spawner uid", read_privilege_state().uid, "| per-cell mode:", per_cell_uid_mode_available())
parent, child = socket.socketpair()
if os.fork() == 0:
    parent.close()
    serve_spawner(child, SpawnPolicy(binary=Path("/usr/local/bin/python3"), stack_root=Path("/tmp")))
    os._exit(0)
child.close()
parent.send(json.dumps({
    "uid": 20001, "gid": 20001,
    "argv": ["/usr/local/bin/python3", "/probe.py"], "cwd": "/tmp", "env": {},
}).encode())
pid, io = receive_spawn_result(parent)
print("cell pid", pid, "spawned")
for _ in range(60):
    if os.path.exists("/tmp/j7.out"):
        break
    time.sleep(0.2)
if os.path.exists("/tmp/j7.out"):
    print(open("/tmp/j7.out").read())
else:
    os.set_blocking(io[2], False)
    os.set_blocking(io[1], False)
    time.sleep(0.5)
    for label, fd in (("stdout", io[1]), ("stderr", io[2])):
        try:
            data = os.read(fd, 8192)
        except BlockingIOError:
            data = b""
        print("cell", label + ":", data.decode(errors="replace")[:900] or "(empty)")
sys.stdout.flush()
os._exit(0)
