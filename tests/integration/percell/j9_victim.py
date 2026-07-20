"""Cell B: honest. Writes its config, then re-reads it to prove it survived."""
import os, time
home = "/cells/slot-1"
body = ('model_provider = "boltrig_model_proxy"\n'
        '[model_providers.boltrig_model_proxy.auth]\n'
        'command = "/opt/boltrig/codex/model_auth_helper"\n')
with open(home + "/config.toml", "w") as fh:
    fh.write(body)
os.chmod(home + "/config.toml", 0o600)
open("/tmp/b-ready", "w").write(str(os.getuid()))
time.sleep(12)   # let the attacker have its turn
after = open(home + "/config.toml").read()
open("/tmp/b-verdict", "w").write(
    "B uid=%d | config intact: %s | auth.command intact: %s | contents=%r"
    % (os.getuid(), after == body, "model_auth_helper" in after, after[:60]))
