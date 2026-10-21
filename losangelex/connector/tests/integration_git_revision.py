"""Read actual canonical Git metadata; create no per-agent worktrees."""
import json,os,subprocess,time
from pathlib import Path
from lax_connector.collaboration_resources import revision
root=Path(os.environ["GIT_REVISION_EVIDENCE"]);root.mkdir(mode=0o700)
checks=[]
for name in ["lax","hollywood"]:
 p=Path("/aosp/development/lax-three-context-20261018-r01")/name
 expected=subprocess.check_output(["git","-C",str(p),"rev-parse","HEAD"],text=True).strip()
 assert revision(str(p))==expected
 checks.append({"repository":name,"revision":expected,"existingCanonicalMetadata":True})
ordinary=root/"ordinary";ordinary.mkdir()
subprocess.run(["git","-c","init.defaultBranch=qualification","init","-q",str(ordinary)],check=True)
(ordinary/"README").write_text("Disposable real Git revision fixture\n")
subprocess.run(["git","-C",str(ordinary),"add","README"],check=True)
subprocess.run(["git","-C",str(ordinary),"-c","user.name=Qualification","-c","user.email=qualification@example.invalid","commit","-qm","Initial fixture"],check=True)
expected=subprocess.check_output(["git","-C",str(ordinary),"rev-parse","HEAD"],text=True).strip()
assert revision(str(ordinary))==expected
checks.append({"normalGitDirectory":True,"revision":expected})
foreign=root/"foreign";foreign.mkdir()
(foreign/".git").write_text((Path("/aosp/development/lax-three-context-20261018-r01/lax")/".git").read_text())
try:revision(str(foreign))
except ValueError:checks.append({"foreignCheckoutRegistrationRejected":True})
else:raise AssertionError("Foreign metadata accepted")
link=root/"link";link.mkdir();(link/".git").symlink_to(ordinary/".git",target_is_directory=True)
try:revision(str(link))
except ValueError:checks.append({"symlinkMetadataRejected":True})
else:raise AssertionError("Symlink metadata accepted")
result={"at":time.time(),"passed":True,"checks":checks,"worktreesCreated":0,"modelCalls":0,"sourceFilesChangedByTest":False}
(root/"result.json").write_text(json.dumps(result,indent=2)+"\n")
print(json.dumps({"passed":True,"checks":len(checks),"worktreesCreated":0}))
