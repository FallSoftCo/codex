import json,os,subprocess,time
from pathlib import Path
from lax_connector import purpose_install,native_startup
from lax_connector.journal import saved
A='e488f19b-0f60-46ca-bd48-4fe544f06757';G='2d4a0daa-0514-475e-be1e-71decacbd5bc'
C=Path('/var/lib/lax-existing-global-adoption-20261021-r266/cutover-r267');R=Path('/var/lib/harness')/A/'purpose-agents'/G
os.umask(0o077)
e=json.loads((C/'actual-uid-environment.json').read_text())['checks']
assert all(e[x].get('exitCode')==0 for x in ['sudo','github','system76','phone']) and all(e[x]['readable'] and e[x]['gitHead'] for x in ['laxSource','hollywoodSource']) and e['computerUse']['fiveRequiredPresent']
assert not (C/'native-global-start-intent.json').exists(),'Inspect original native activation'
manifest=json.loads((R/'installation.json').read_text());config=json.loads(Path(manifest['config']).read_text())
w=Path(config['workspace'])
if not (w/'.git').exists():
 assert not list(w.iterdir()),'Fresh private workspace has unreviewed content'
 p=subprocess.run(['runuser','-u',manifest['linuxUser'],'--','git','init',str(w)],check=True,capture_output=True,text=True)
 saved(C/'private-workspace-git-initialized.json',{'at':time.time(),'workspace':str(w),'emptyRepository':True,'sourceOrExpectedOutputSeeded':False})
startup=native_startup.prepare(R,manifest,[{'unit':'lax-host-e488f19b0f60.service'},{'unit':'lax-collaboration-e488f19b-ec32d149.service'}],['hollywood-backbone.service'])
saved(C/'native-global-start-intent.json',{'at':time.time(),'units':manifest['units'],'otherPlacementsPaused':True,'noBusinessTaskRequested':True})
active=purpose_install.activate(A,G)
enabled=native_startup.set_enabled(R,startup,True)
saved(C/'native-global-started.json',{'at':time.time(),'activation':active,'startup':enabled,'installerModelSubmissions':0})
print(json.dumps({'activation':active,'bootTarget':enabled['unit'],'bootState':enabled['bootState'],'next':'Inspect original three context bindings; perform disclosed bounded actual human API work'}))
