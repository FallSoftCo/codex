import json,os,time
from pathlib import Path
from lax_connector import collaboration_install
from lax_connector.journal import saved
A='e488f19b-0f60-46ca-bd48-4fe544f06757';G='2d4a0daa-0514-475e-be1e-71decacbd5bc';H='ec32d149-b563-589f-87c9-d5f468df1e79'
R=Path('/var/lib/lax-existing-global-adoption-20261021-r266');C=R/'cutover-r267'
os.umask(0o077)
assert (C/'purpose-prepared.json').exists()
assert not (C/'collaboration-apply-intent.json').exists(),'Inspect original collaboration apply before continuing'
manifest=json.loads((Path('/var/lib/harness')/A/'purpose-agents'/G/'installation.json').read_text())
config=json.loads(Path(manifest['config']).read_text())
spec={'schema':'lax-collaboration-install/v1','controllerConfig':str(Path('/var/lib/harness')/A/'hosts'/H/'controller.json'),'administratorConfig':str(R/'administrator.json'),'interpreter':'/opt/harness/native-existing-realm-20261021-r265/venv/bin/python','resources':[{'name':'global-private','root':config['workspace'],'environmentId':'local'},{'name':'lax-source','root':'/aosp/development/lax-three-context-20261018-r01/lax','environmentId':'local'},{'name':'hollywood-source','root':'/aosp/development/lax-three-context-20261018-r01/hollywood','environmentId':'local'}],'agents':{G:{'resources':['global-private','lax-source','hollywood-source'],'defaultResource':'global-private'}}}
saved(C/'collaboration-spec.json',spec)
prepared=collaboration_install.prepare(spec,C/'collaboration-prepared')
saved(C/'collaboration-apply-intent.json',{'at':time.time(),'prepared':prepared,'modelsStarted':0})
result=collaboration_install.apply(C/'collaboration-prepared')
saved(C/'collaboration-applied.json',result)
print(json.dumps(result))
