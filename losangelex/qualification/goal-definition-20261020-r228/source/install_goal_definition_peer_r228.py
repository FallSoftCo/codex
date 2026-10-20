"""Install one real producer per fresh arm, no model/task starts."""
import json,secrets,time,subprocess,hashlib
from pathlib import Path
from uuid import uuid4
from lax_connector.host import request,machine_identity
from lax_connector.purpose_install import install,directory,protected
from lax_connector.collaboration_capture import administrative_put
from lax_connector.journal import saved
ROOT=Path('/var/lib/lax-operating-model-comparison-20261020-r228')
base=protected('/var/lib/harness/483b0ac5-072a-43e1-ab50-36405f83de31/purpose-agents/cccfd79e-e934-460a-886e-df51c3ded886/installation.json')
auth=str(Path(protected(base['config'])['homes']['writer'])/'auth.json')
for name in ['definition','ordinary']:
 out=ROOT/name;arm=protected(out/'public.json');plan=protected(out/'installation-intent.json')
 peerout=out/'peer';assert not peerout.exists(),'Inspect original producer installation; do not replay'
 peerout.mkdir(mode=0o700);(peerout/'administration').mkdir(mode=0o700)
 info={'agentId':str(uuid4()),'workspaceId':str(uuid4()),'contextIds':{p:str(uuid4()) for p in ['reader','writer','responder']},'tokens':{p:secrets.token_urlsafe(40) for p in ['reader','writer','responder']},'credential':secrets.token_urlsafe(40)}
 noise={'id':str(uuid4()),'token':secrets.token_urlsafe(40)}
 saved(peerout/'identity.json',info);saved(peerout/'fixture-agent.json',noise)
 call=lambda method,path,body=None:request('http://127.0.0.1:18783',plan['credentials']['Owner']['token'],method,path,body)
 def put(path,body,method='PUT'):return administrative_put(peerout,call,path,body,method=method)
 prefix='operating-model-r228:'+name+':'
 put('principals',{'operationId':prefix+'producer','id':info['agentId'],'name':'Disposable language-practice policy engineer','kind':'agent','enrollmentCredential':info['credential']},'POST')
 put('principals',{'operationId':prefix+'fixture','id':noise['id'],'name':'Explicit nonmodel room-traffic fixture','kind':'agent','enrollmentCredential':noise['token']},'POST')
 for who in [info['agentId'],noise['id']]:
  put('rooms/'+arm['room']+'/membership',{'operationId':prefix+'member:'+who,'principalId':who,'can_read':True,'can_post':True,'can_request':True,'revision':0})
 role=call('GET','agents/'+info['agentId']+'/role')
 put('agents/'+info['agentId']+'/role',{'operationId':prefix+'role','revision':role['revision'],'primary':'engineer','purpose':'Implement and verify the assigned language-practice eligibility policy artifact. Communicate exact current policy and evidence to the enrolled room as normal attributable engineering updates. Do not direct the report agent or grade its work. This is disposable qualification; do not edit another agent workspace or operate production, customers, credentials, old work or services.','homeRoomId':arm['room']})
 put('placements',{'operationId':prefix+'placement','hostId':arm['host'],'name':'OZZZ-OS private room qualification','identityFingerprint':machine_identity(),'capabilities':{'purposeNative':True,'model':'gpt-6.1-sol'},'agentId':info['agentId']},'POST')
 bindings=[{'purpose':p,'contextId':info['contextIds'][p],'credentialDigest':hashlib.sha256(json.dumps(t,sort_keys=True,separators=(',',':')).encode()).hexdigest()} for p,t in info['tokens'].items()]
 put('agents/'+info['agentId']+'/context-system',{'operationId':prefix+'contexts','hostId':arm['host'],'workspaceId':info['workspaceId'],'bindings':bindings})
 spec={**info,'authorityId':arm['authority'],'hostId':arm['host'],'hollywoodUrl':'http://127.0.0.1:18783','machineIdentity':machine_identity(),'approvedModelAuthFile':auth,'binary':'/opt/lax-native-pilot-20261020-r172/native/bin/codex-app-server','interpreter':'/opt/lax-three-context-20261018-r01/venv-r212/bin/python','pythonRoot':'/opt/lax-three-context-20261018-r01/venv-r212','model':'gpt-6.1-sol','effort':'xhigh','serviceMemoryMaxBytes':8*1024**3,'nativeCollaborationChannel':'/etc/harness/'+arm['authority']+'/collaboration/'+arm['host']+'/channel.json'}
 saved(peerout/'spec.json',spec);installed=install(spec);saved(peerout/'install-result.json',installed)
 manifest=protected(directory(arm['authority'],info['agentId'])/'installation.json');cfg=protected(manifest['config'])
 public={'authority':arm['authority'],'agent':info['agentId'],'host':arm['host'],'room':arm['room'],'config':manifest['config'],'workspace':cfg['workspace'],'linuxUser':manifest['linuxUser'],'uid':manifest['uid'],'gid':manifest['gid'],'units':manifest['units'],'installation':str(directory(arm['authority'],info['agentId'])/'installation.json'),'state':'prepared-stopped','modelsStarted':0}
 saved(peerout/'public.json',public)
 print(json.dumps({'arm':name,'producer':public,'modelsStarted':0}),flush=True)
