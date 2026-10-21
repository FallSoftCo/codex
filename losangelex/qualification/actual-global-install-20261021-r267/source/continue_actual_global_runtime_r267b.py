import hashlib,json,os,time
from pathlib import Path
from lax_connector.host import request
from lax_connector.collaboration_capture import administrative_put
from lax_connector import purpose_install
from lax_connector.environment import validate
from lax_connector.journal import saved
ROOT=Path('/var/lib/lax-existing-global-adoption-20261021-r266');CUT=ROOT/'cutover-r267'
A='e488f19b-0f60-46ca-bd48-4fe544f06757';G='2d4a0daa-0514-475e-be1e-71decacbd5bc'
def save(p,v):p.write_text(json.dumps(v,indent=2,default=str)+'\n');p.chmod(0o600)
def main():
 os.umask(0o077);assert (CUT/'api-upgraded.json').exists()
 assert (CUT/'prepare-transition-intent.json').exists() and not (CUT/'administration').exists(),'Original failure must be inspected before continuation'
 assert not (CUT/'prepare-continuation-r267b.json').exists(),'Inspect continuation before retry'
 admin=json.loads((ROOT/'administrator.json').read_text())
 http=lambda method,path,payload=None:request(admin['hollywoodUrl'],admin['token'],method,path,payload)
 places=json.loads((CUT/'placements.before.json').read_text())
 assert len(places)==12
 save(CUT/'prepare-continuation-r267b.json',{'at':time.time(),'action':'Explicit old-agent pause, existing Global role owner enrollment and prepared native installation; not activation'})
 (CUT/'administration').mkdir(mode=0o700)
 holds=[]
 for place in places:
  agent=place['agent']
  if agent==G:continue
  current=http('GET','placements/'+agent)['placement']
  assert current['host']==place['host'] and current['generation']==place['generation'] and current['revision']==1 and current['enabled']==place['enabled'],'Original placement changed; schema migration initializes revision=1, generation retained'
  if current['enabled']:
   result=administrative_put(CUT,http,'placements/'+agent,{'operationId':'hold-native-migration:'+agent+':r267','hostId':place['host'],'revision':current['revision'],'enabled':False})
   holds.append({'agentId':agent,'revision':result['placement']['revision'],'state':result['state']})
 save(CUT/'legacy-placement-holds.json',{'at':time.time(),'placements':holds,'requestsReposted':0,'modelsStarted':0})
 role=json.loads((CUT/'role-owner-request.json').read_text())
 result=administrative_put(CUT,http,'agents/'+G+'/role',role)
 save(CUT/'role-owner-enrolled.json',{'at':time.time(),'role':result,'userStopIntentIncluded':True})
 contexts=json.loads((ROOT/'context-enrollment-request.json').read_text())
 enrolled=administrative_put(CUT,http,'agents/'+G+'/context-system',contexts)
 save(CUT/'contexts-enrolled.json',{'at':time.time(),'result':enrolled,'legacyNativeHistoryRetained':True})
 envplan=json.loads(Path('/var/lib/lax-live-promotion-preview-20261021-r260/existing-realm-rollout-r265.json').read_text())
 live=Path('/etc/harness')/A/'environment.json';candidate=Path(envplan['environmentCandidate']['path'])
 assert hashlib.sha256(live.read_bytes()).hexdigest()==envplan['environmentCandidate']['expectedLiveSha256'],'Live routes changed; inspect'
 assert hashlib.sha256(candidate.read_bytes()).hexdigest()==envplan['environmentCandidate']['candidateSha256']
 new=validate(json.loads(candidate.read_text()),A);saved(live,new);live.chmod(0o644)
 save(CUT/'environment-reconciled.json',{'at':time.time(),'oldSha256':envplan['environmentCandidate']['expectedLiveSha256'],'newSha256':hashlib.sha256(live.read_bytes()).hexdigest(),'githubSshBuildAndNextcompOwnershipRetained':True})
 spec=json.loads((ROOT/'purpose-spec.json').read_text())
 prepared=purpose_install.install(spec,prepare_only=True)
 save(CUT/'purpose-prepared.json',prepared)
 print(json.dumps({'phase':'purpose-prepared','agentId':G,'legacyPlacementsPaused':len(holds),'contextEnrollment':enrolled,'linuxUser':prepared['linuxUser'],'sudoVerifiedUid':prepared['sudoVerifiedUid'],'servicesStarted':prepared['servicesStarted'],'modelsStarted':0}))
if __name__=='__main__':main()
