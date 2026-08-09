# AppArmor: `boltrig-codex`

Install this on any **Ubuntu 24.04 or later** host that runs a stack with
`BOLTRIG_CODEX_TRUSTED=1`. Without it the kernel and fleet-worker refuse to boot.

```sh
sudo cp deploy/apparmor/boltrig-codex /etc/apparmor.d/boltrig-codex
sudo apparmor_parser -r -W /etc/apparmor.d/boltrig-codex
```

Then give the two services both of these, in the tenant overlay:

```yaml
    security_opt:
      - seccomp:unconfined
      - apparmor:boltrig-codex
```

## Why both, and why not the obvious shortcuts

The kernel proves at boot that it can enforce the codex cell wall, and that proof
shells out to bubblewrap. On 24.04 that hits **two** separate blocks, one after
the other, so fixing the first makes the second look like a new bug.

Measured on `jellytot-prod` (Ubuntu 24.04.4, kernel 6.8.0-136) against the real
`prove_sandbox_engagement`, each grant moving the failure exactly one step:

| security opts | result |
|---|---|
| `docker-default` (default) | `bwrap: No permissions to create new namespace` |
| `+ seccomp:unconfined` | `bwrap: Failed to make / slave: Permission denied` |
| `+ apparmor:boltrig-codex` (mount, umount) | `bwrap: pivot_root: Permission denied` |
| `+ pivot_root` in the profile | **PROOF_OK** |

**`seccomp:unconfined` alone is not enough**, and neither is the profile alone.
Ubuntu 24.04 transitions any process that creates an unprivileged user namespace
into an `unprivileged_userns` profile which denies `CAP_SYS_ADMIN`, so bwrap gets
its namespace and then cannot mount inside it. The audit line is explicit:

```
apparmor="DENIED" operation="capable" profile="unprivileged_userns"
comm="unshare" capability=21 capname="sys_admin"
```

Carrying `userns,` in a **named** profile stops that transition.

### Do not use `apparmor=unconfined`

It is strictly **worse** than `docker-default` here. 24.04 allowlists confined
docker profiles for userns, and going unconfined loses the allowance:

| | userns |
|---|---|
| `seccomp=unconfined` | OK |
| `seccomp=unconfined` + `apparmor=unconfined` | **REFUSED** |

### Do not reach for the host sysctl

`kernel.apparmor_restrict_unprivileged_userns=0` is the documented Ubuntu escape
hatch and it does work, but it removes the boundary for **every process on the
box**, not just the one that needs it. On a shared host that includes unrelated
tenants. This profile is the targeted equivalent.

### Beware the probe that proves nothing

`unshare -Ur true` returns OK under `seccomp=unconfined` at every uid, with
`cap_drop ALL` and `no-new-privileges`. It creates the namespace and exits
**without mounting**, so it never reaches the second block. Test with bwrap
itself, or better, with `prove_sandbox_engagement` in a throwaway container:

```sh
docker run --rm --user 10001 --read-only --cap-drop ALL \
  --security-opt seccomp=unconfined --security-opt apparmor=boltrig-codex \
  --security-opt no-new-privileges:true \
  --tmpfs /tmp --tmpfs /var/lib/boltrig/codex-cells:mode=0711,uid=10001,gid=10001 \
  --env-file <(docker inspect <kernel> -f '{{range .Config.Env}}{{println .}}{{end}}' | grep ^BOLTRIG_CODEX) \
  --entrypoint python <image> -c 'from pathlib import Path; import os
from boltrig.fleet.infrastructure.codex_sandbox_engagement import prove_sandbox_engagement
prove_sandbox_engagement(codex_binary=Path(os.environ["BOLTRIG_CODEX_BINARY"]),
                         probe_root=Path(os.environ["BOLTRIG_CODEX_STACK_ROOT"]))
print("PROOF_OK")'
```

## What the profile changes

`docker-default` with three additions: `mount,` / `umount,`, `userns,` and
`pivot_root,`. **Every `docker-default` denial is preserved verbatim** - the
`@{PROC}` write denials, `sysrq-trigger`, `kcore`, the `/sys` restrictions, and
ptrace confined to peers of the same profile.

It is not in `docker-compose.yml` because the profile must exist on the host
first, and a compose file that references a missing AppArmor profile fails to
start the container. It belongs in each host's tenant overlay, after installing
it here.
