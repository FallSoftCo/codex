"""Installed SSH route client; provider credentials stay in their owning account."""
import os,sys
from .environment_identity import current
from .environment import snapshot

def main():
    identity=current()
    if not identity:
        raise PermissionError("Installed agent identity required")
    if sys.argv[1:2]!=["ssh"]:
        raise ValueError("SSH route required")
    args=sys.argv[2:]
    profile=snapshot(identity["authorityId"])
    routes={r["name"]:r["command"] for r in profile.get("facts",{}).get("sshRoutes",[])}
    # Alias-first calls use the approved explicit argv. Other SSH use remains
    # ordinary OpenSSH; installation routes are conveniences, not a policy engine.
    if args and args[0] in routes:
        command=routes[args[0]]+args[1:]
        os.execvp(command[0],command)
    os.execv("/usr/bin/ssh",["/usr/bin/ssh",*args])

if __name__=="__main__":
    main()
