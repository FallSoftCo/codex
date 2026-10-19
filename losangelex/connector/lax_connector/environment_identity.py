"""Resolve installation authority from the actual NSS execution identity."""
import os,pwd
from pathlib import Path
from uuid import UUID

def current():
    account=pwd.getpwuid(os.geteuid())
    parts=Path(account.pw_dir).parts
    if len(parts)==8 and parts[:4]==("/", "var", "lib", "harness") and parts[7]=="home":
        authority=str(UUID(parts[4]));agent=str(UUID(parts[6]))
        if parts[5]=="purpose-agents":
            slug=authority.replace("-","")[:8]+"-"+agent.replace("-","")[:12]
            if account.pw_name not in ("hglobal-"+slug,"hagent-"+slug):
                raise PermissionError("Purpose execution identity differs")
        elif parts[5]=="workers":
            if not account.pw_name.startswith("hworker-"):
                raise PermissionError("Worker execution identity differs")
        else:return None
        return {"authorityId":authority,"agentId":agent,"account":account}
    return None
