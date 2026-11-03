"""Read actual existing parent/native pins; prepare ONLY disposable QA files.
No canonical agent is enrolled/initialized, no native RPC/model/session attached.
"""
import hashlib,json,os,pathlib,pwd,shutil,sys,datetime,time
from uuid import uuid4
B=pathlib.Path(__file__).resolve().parent;sys.path.insert(0,str(B/'source/losangelex/connector'))
from lax_connector import room_factory_macos as f
from lax_connector.room_tools import TOOLS
S=pathlib.Path('/Users/lume/.local/state/lax-host-20261101-r01');R=pathlib.Path('/Users/lume/Development/room-factory-macos-20261103-r01')
sha=lambda p:hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
pin=lambda p:{'path':str(p),'sha256':sha(p)}
os.umask(0o077)
qa=B/'qa-private';assert not qa.exists();qa.mkdir(mode=0o700)
root=qa/'agentRoot';root.mkdir(mode=0o700);operation=qa/'operation';operation.mkdir(mode=0o700)
mfile=S/'native-manifest.json';parentfile=S/'global-config.private.json';ownerfile=S/'global-receipt.json'
m=json.loads(mfile.read_text());parent=json.loads(parentfile.read_text());owner=json.loads(ownerfile.read_text())
previous=json.loads((R/'route-evidence.json').read_text());old={x['label']:x for x in previous['currentServices']}
native=f.process_identity(old[m['unit']]['pid']);host=f.process_identity(old['co.fallsoft.lax.global.20261101-r01']['pid'])
assert time.strftime('%a %b %e %H:%M:%S %Y', time.localtime(float(native['birth']))) in old[m['unit']]['processIdentity']
assert time.strftime('%a %b %e %H:%M:%S %Y', time.localtime(float(host['birth']))) in old['co.fallsoft.lax.global.20261101-r01']['processIdentity']
original={str(p):sha(p) for p in [mfile,parentfile,ownerfile]}
account=pwd.getpwuid(os.geteuid());alias=pathlib.Path(m['socket']);target=alias.resolve(strict=True)
policy={'schema':'lax-macos-room-account/v1','uid':os.geteuid(),'user':account.pw_name,'serviceHome':account.pw_dir,
        'authorityId':m['authorityId'],'hostId':m['hostId'],'ownerAgentId':m['ownerAgentId'],
        'initialPermissions':{'sandbox':'danger-full-access','approvalPolicy':'never'},
        'nativeManifest':pin(mfile),'parentConfig':pin(parentfile),'ownerReceipt':pin(ownerfile),
        'agentRoot':str(root),'agentRootIdentity':f.identity(root),'nativeProcess':native,'parentProcess':host,
        'interpreter':pin(pathlib.Path(host['image']).resolve()),'binary':pin(m['binary']),
        'nativeSocketPin':{'schema':'lax-native-ipc-alias/v1','alias':f.identity(alias),'linkText':os.readlink(alias),
                          'targetPath':str(target),'target':f.identity(target),'targetParent':f.identity(target.parent)}}
policyfile=qa/'QA-ONLY-policy.json';policyfile.write_text(json.dumps(policy,indent=2));policyfile.chmod(0o600)
scope={'operationId':'QA-ONLY-parent-files-source-qualification','authorityId':m['authorityId'],'hostId':m['hostId'],
       'nodeId':m['hostId'],'originRoomId':str(uuid4()),'agentId':str(uuid4())}
home=root/scope['agentId']
c={'runtimeMode':'room-conversation','authorityId':m['authorityId'],'hostId':m['hostId'],'agentId':scope['agentId'],
   'nativeServer':parent['nativeServer'],'codexHome':m['codexHome'],'binary':m['binary'],
   'state':str(home/'state'),'workspace':str(home/'work'),'rooms':[{'roomId':scope['originRoomId'],'after':0}],
   'model':parent.get('model','gpt-6.1-sol'),'effort':parent.get('effort','xhigh'),
   'sandbox':'danger-full-access','approvalPolicy':'never','nativeName':'QA files only, not enrolled',
   'instructions':'Credential-free QA file fixture. No runtime/native action.',
   'conversationResumeInstructions':{'developerInstructions':'Fresh QA role only; no session will be attached.'},
   'token':'SYNTHETIC_QA_NOT_ENROLLED','hollywoodUrl':'http://127.0.0.1:1','conversationDynamicTools':TOOLS}
raw=json.dumps({**scope,'connectorConfig':c},indent=2).encode();helper=f.MacAgentFiles(policyfile,sha(policyfile))
allowed={native['pid'],host['pid']};audited=[]
def audit(event,args):
 if event=='subprocess.Popen':raise AssertionError('Child process dispatch denied')
 if event=='ctypes.dlopen':
  assert args[0]=='/usr/lib/libproc.dylib'
  audited.append({'inProcessSystemLibrary':args[0]})
 if event in ('socket.connect','socket.bind','os.system','os.exec','os.posix_spawn'):raise AssertionError('Native/network/process dispatch denied')
sys.addaudithook(audit)
try:
 before=helper.validate_parent(c)
 prepared=helper.prepare_files(c,scope,operation,raw_spec=raw,expected_spec_sha256=f.digest(raw))
 inspected=helper.prepare_files(c,scope,operation,raw_spec=raw,expected_spec_sha256=f.digest(raw),inspect=True)
 assert prepared==inspected and prepared['sessionAttachmentRequired'] and prepared['osServicesCreated']==prepared['nativeThreadsCreated']==prepared['modelTurnsRequested']==0
 for p,h in original.items():assert sha(p)==h
 assert f.process_identity(native['pid'])==native and f.process_identity(host['pid'])==host
 assert f.identity(alias)==policy['nativeSocketPin']['alias'] and f.identity(target)==policy['nativeSocketPin']['target']
 result={'schema':'macos-resident-room-files-actual-parent-qualification/v1','state':'passed',
         'actualParentEvidence':before,'preparedFilesSha256':f.digest(f.wire(prepared)),
         'configSha256':sha(prepared['initialConfigPath']),'declaredConfigSha256':prepared['initialConfigSha256'],
         'sourceModuleSha256':sha(B/'source/losangelex/connector/lax_connector/room_factory_macos.py'),
         'originalProtectedFilesUnchanged':original,'nativeAndGlobalIncarnationsUnchanged':True,
         'auditedInProcessLibprocLoads':audited,'childProcessesCreated':0,'realNativeRpcCalls':0,'modelTurns':0,'osServiceActions':0,
         'canonicalAgentsEnrolled':0,'logicalSessionsAttached':0,'limits':['QA-only policy/UUIDs and disposable agentRoot, NOT deployment approval.','Actual parent account/manifest/socket/process validated; multi-session supervisor/readiness is common-owner work.']}
finally:
 # Exact disposable QA tree: no native context/session exists and all files were
 # generated by this no-dispatch fixture. Production files live outside it.
 assert qa.is_relative_to(B) and not qa.is_symlink()
 shutil.rmtree(qa)
if 'result' in globals():
 result['ownedQAFileTreeRetired']=not qa.exists();out=B/'actual-parent-qualification.json';out.write_text(json.dumps(result,indent=2)+'\n');out.chmod(0o600)
 print(json.dumps({'state':result['state'],'receiptSha256':sha(out),'actualNativePid':native['pid'],'actualParentPid':host['pid'],'realNativeRpcCalls':0,'osServiceActions':0,'qaFilesRetired':result['ownedQAFileTreeRetired']}))
