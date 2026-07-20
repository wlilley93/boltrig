"""J9: two live cells under the real spawner, hostile A against honest B."""
import os, sys, json, socket, time
from pathlib import Path
from boltrig.fleet.infrastructure.cell_privilege import per_cell_uid_mode_available
from boltrig.fleet.infrastructure.cell_slots import CellSlotAllocator, assert_slots_are_distinct, slot_for_index
from boltrig.fleet.infrastructure.cell_spawner import SpawnPolicy, serve_spawner, receive_spawn_result

print("per-cell mode:", per_cell_uid_mode_available())
assert_slots_are_distinct(tuple(slot_for_index(i) for i in range(4)))
allocator = CellSlotAllocator(4)
a, b = allocator.acquire(), allocator.acquire()
print("slot A uid", a.uid, "| slot B uid", b.uid, "| distinct:", a.uid != b.uid)

parent, child = socket.socketpair()
if os.fork() == 0:
    parent.close()
    serve_spawner(child, SpawnPolicy(binary=Path("/usr/local/bin/python3"), stack_root=Path("/cells")))
    os._exit(0)
child.close()

def spawn(uid, script):
    parent.send(json.dumps({
        "uid": uid, "gid": uid,
        "argv": ["/usr/local/bin/python3", "-u", script], "cwd": "/cells", "env": {},
    }).encode())
    return receive_spawn_result(parent)[0]

# B first, so the victim's config exists before the attacker runs.
pid_b = spawn(b.uid, "/victim.py")
time.sleep(1.0)
pid_a = spawn(a.uid, "/attacker.py")
print("cell A pid", pid_a, "(uid %d, hostile) | cell B pid" % a.uid, pid_b, "(uid %d, honest)" % b.uid)

for _ in range(100):
    if os.path.exists("/tmp/j9.out"):
        break
    time.sleep(0.2)
print()
print(open("/tmp/j9.out").read() if os.path.exists("/tmp/j9.out") else "NO ATTACKER OUTPUT")
print()
# The driver is uid 0 but holds NO CAP_DAC_OVERRIDE (cap_drop ALL), so it cannot
# traverse B's 0700 slot either. That is the boundary working, not a failure, and
# an earlier version of this check misread it as "config missing". So B verifies
# its own file: the only party that can read B's slot is B.
for _ in range(80):
    if os.path.exists("/tmp/b-verdict"):
        break
    time.sleep(0.2)
print(open("/tmp/b-verdict").read() if os.path.exists("/tmp/b-verdict") else "NO VERDICT FROM B")
try:
    os.listdir("/cells/slot-1")
    print("driver (uid 0) could list B's slot: yes - CAP_DAC_OVERRIDE is present")
except PermissionError:
    print("driver (uid 0, no CAP_DAC_OVERRIDE) could list B's slot: refused, as expected")
sys.stdout.flush()
os._exit(0)
