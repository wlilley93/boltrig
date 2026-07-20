import os, sys
r = []
def t(label, fn):
    try:
        fn(); r.append(label + ": ESCALATED (BAD)")
    except (PermissionError, OSError, FileNotFoundError):
        r.append(label + ": refused")

t("setuid(0) back to the spawner", lambda: os.setuid(0))
t("setuid(10001) to the API", lambda: os.setuid(10001))
t("setuid(20002) sideways to a sibling", lambda: os.setuid(20002))

# execve REPLACES the process, so it must be forked or the probe never reports.
# The first version of this probe did not, which is why it produced no output at
# all: su had already taken over the process and was sitting at a password prompt.
kid = os.fork()
if kid == 0:
    devnull = os.open("/dev/null", os.O_RDWR)
    os.dup2(devnull, 0); os.dup2(devnull, 1); os.dup2(devnull, 2)
    try:
        os.execve("/usr/bin/su", ["su", "root"], {})
    except OSError:
        os._exit(3)
    os._exit(4)
_, status = os.waitpid(kid, 0)
# su without a setuid bit cannot change uid; it degrades to asking for a password
# and exits nonzero. A ZERO exit here would mean it really did become root.
r.append("execve /usr/bin/su -> exit %s (%s)" % (
    os.waitstatus_to_exitcode(status),
    "refused" if os.waitstatus_to_exitcode(status) != 0 else "ESCALATED (BAD)"))

s = open("/proc/self/status").read()
f = {l.split(":")[0]: l.split(":")[1].strip() for l in s.splitlines() if ":" in l}
r.append("uid=%s CapPrm=%s CapEff=%s CapAmb=%s NoNewPrivs=%s" % (
    f["Uid"].split()[0], f["CapPrm"], f["CapEff"], f.get("CapAmb"), f["NoNewPrivs"]))
open("/tmp/j7.out", "w").write("\n".join(r))
