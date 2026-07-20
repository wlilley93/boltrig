"""Cell A: hostile. Holds full write access to everything ITS uid can reach and
tries to take cell B's bearer by the config.toml vector the court named."""
import os, time
r = []
def t(label, fn):
    try:
        fn(); r.append(label + ": SUCCEEDED (BAD)")
    except (PermissionError, OSError, FileNotFoundError) as e:
        r.append("%s: refused (%s)" % (label, e.__class__.__name__))

for _ in range(80):                      # wait for B to exist
    if os.path.exists("/tmp/b-ready"):
        break
    time.sleep(0.2)

victim = "/cells/slot-1/config.toml"
own = "/cells/slot-0/config.toml"

# A can do whatever it likes inside its OWN slot. That is expected and fine.
os.makedirs("/cells/slot-0", exist_ok=True)
try:
    open(own, "w").write("mine\n")
    r.append("write its OWN config.toml: succeeded (EXPECTED, a cell owns its slot)")
except OSError as e:
    r.append("write its OWN config.toml: refused (%s) - UNEXPECTED" % e.__class__.__name__)

# THE VECTOR: rewrite B's auth.command so B's App Server execs attacker code and
# hands over B's (cross-tenant) bearer. This is the exact attack VJS-CC-VJS 5
# found, and the whole grant exists to stop it.
t("rewrite B's config.toml", lambda: open(victim, "w").write("pwned\n"))
t("append to B's config.toml", lambda: open(victim, "a").write("pwned\n"))
t("read B's config.toml", lambda: open(victim).read())
t("unlink B's config.toml", lambda: os.unlink(victim))
t("replace B's config.toml by rename", lambda: os.rename(own, victim))
t("chmod B's config.toml", lambda: os.chmod(victim, 0o666))
t("create a NEW file in B's slot", lambda: open("/cells/slot-1/evil.toml", "w").write("x"))
t("list B's slot", lambda: os.listdir("/cells/slot-1"))
t("chown B's slot to itself", lambda: os.chown("/cells/slot-1", os.getuid(), os.getuid()))

r.append("attacker uid=%d" % os.getuid())
open("/tmp/j9.out", "w").write("\n".join(r))
