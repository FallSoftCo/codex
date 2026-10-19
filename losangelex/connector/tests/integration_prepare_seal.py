import json,time,subprocess
from pathlib import Path
from lax_connector.purpose_readiness import verify
from lax_connector.purpose_install import protected,directory,activate
authority='f96e5615-0e6d-48d3-93b6-dc54393d5c2e'
agents=['f2363d21-e7da-4dc5-8749-6736d01d4f68','3df5ce3f-334d-5942-b99b-84fe7436bd19','e4c5bc4f-8d3e-5fcf-ac11-44722b1efb1d']
q=Path('/aosp/development/lax-three-context-20261018-r01/qualification');out=q/'prepare-seal-read-only-r43.json'
if out.exists():raise RuntimeError('Inspect original qualification')
units=['hollywood-backbone.service','nextcomp-native-core.service']
manifests={a:protected(directory(authority,a)/'installation.json') for a in agents}
units += [u for m in manifests.values() for u in m['units'].values()]
def pids():return {u:subprocess.check_output(['systemctl','show',u,'-p','MainPID','--value'],text=True).strip() for u in units}
before=pids();results={}
for a,m in manifests.items():
 old=(directory(authority,a)/'activation-intent.json').read_bytes()
 results[a]=verify(m)
 # Existing recorded activation remains status-only; no setup retry can start it.
 status=activate(authority,a)
 assert status['activationRepeated'] is False
 assert (directory(authority,a)/'activation-intent.json').read_bytes()==old
assert pids()==before
value={'schema':'purpose-prepare-seal-read-only/v1','at':time.time(),'mode':'Source candidate verified actual three QA Unix identities, sealed-dependency checks via authenticated canonical reads and protected live bridge peer. No seal written, installation replay, unit/config/identity changes, model/service start or restart. This is not a clean first-install/bootstrap proof.','results':results,'existingActivationRemainsStatusOnly':True,'protectedPidsUnchanged':before,'productionChanged':False,'phoneChanged':False}
out.write_text(json.dumps(value,indent=2)+'\n');print(json.dumps({'at':value['at'],'actualIdentities':len(results),'localNativeDependenciesVerified':True,'existingActivationRemainsStatusOnly':True,'protectedPidsUnchanged':True,'sourceCandidateOnly':True},indent=2))

