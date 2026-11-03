"""Synthetic owner/incarnation fixtures ONLY; no real approval or native call."""
import asyncio,copy,hashlib,importlib.util,json,sys,time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
S=Path(__file__).parent;P=S.parent;W=P.parent
F=P/'frozen-source/source/losangelex/connector/lax_connector'
BASE=W/'windows-room-factory-56611f4a-r01/base246/losangelex/connector'
sys.path.insert(0,str(BASE))
import lax_connector
lax_connector.__path__.insert(0,str(F));lax_connector.__path__.insert(0,str(S))
from lax_connector import room_factory_windows_state as platform
Q=S/'qualification-r01'
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def save(path,value):platform.once(path,value)
def replace_fixture(path,value):
    # These are plainly synthetic owner records, never original BLD policy.
    from lax_connector.journal import saved
    saved(path,value)
def held(call):
    try:call()
    except (platform.Held,PermissionError,FileNotFoundError):return True
    raise AssertionError('Expected fail-closed original/owner/incarnation guard')
async def run():
    assert not Q.exists(),'Inspect original fixture; do not repeat it'
    platform.create_private_directory(Q)
    sources=json.loads((S/'SOURCE-PINS.json').read_text())
    assert all(sha(S/n)==v['candidateSha256'] for n,v in sources['files'].items())
    save(Q/'frozen-source.json',sources)
    for name in ('profile','native-state','native-work','agents','parent-records','parent-state'):
        platform.create_private_directory(Q/name)
    authority,host,parent_id,child_id,room=[str(uuid4()) for _ in range(5)]
    # These fictional identities deliberately cannot name the live BLD runtime.
    pa={'pid':10101,'created':'SYNTHETIC-PARENT-A','image':str(Q/'fixture-parent.exe'),'ownerSidSha256':'fixture-sid','sessionId':1}
    pb={**pa,'pid':20202,'created':'SYNTHETIC-PARENT-B'}
    native={'pid':30303,'created':'SYNTHETIC-NATIVE','image':str(Q/'fixture-native.exe'),'ownerSidSha256':'fixture-sid','sessionId':1}
    active={'parent':pa}
    old_process,old_peer=platform.process,platform.native_peer
    platform.process=lambda pid:dict(active['parent']) if pid==active['parent']['pid'] else (_ for _ in ()).throw(AssertionError('No actual process permitted'))
    platform.native_peer=lambda manifest:dict(native)
    manifest={'schema':'lax-native-host/v1','platform':'windows','runtimeMode':'room-conversation',
        'authorityId':authority,'hostId':host,'ownerAgentId':parent_id,'binary':native['image'],
        'codexHome':str(Q/'profile'),'state':str(Q/'native-state'),'workspace':str(Q/'native-work'),'socket':str(Q/'not-a-real-native.sock')}
    manifestfile=Q/'native.private.json';save(manifestfile,manifest)
    metadata=Q/'parent-records/python.json';save(metadata,{'state':'running','pid':pa['pid']})
    fields={'authorityId':authority,'hostId':host,'parentAgentId':parent_id,
        'nativeHostManifestSha256':sha(manifestfile),'parentTaskName':'SYNTHETIC-NOT-A-TASK'}
    acceptance_path=Q/'parent-records/owner-acceptance.private.json'
    def accepted(which,policy_hash,schema='v2'):
        return {'schema':'lax-windows-parent-runtime-acceptance/'+schema,**fields,'state':'running',
            'admissionAllowed':True,'runtimeIdentity':which,'nativeIdentity':native,
            'parentArgvSha256':'fixture-argv-'+str(which['pid']),'policySha256':policy_hash,
            'ownerAcceptanceOperationId':'SYNTHETIC-FIXTURE-OWNER-'+str(which['pid'])}
    legacy_accept=accepted(pa,'not-v1-policy-bound','v1');save(acceptance_path,legacy_accept)
    policy={'schema':'lax-windows-room-parent-policy/v1',**fields,
        'ownerSidSha256':platform.digest(platform.current_owner().encode()),'agentRoot':str(Q/'agents'),
        'nativeHostManifest':str(manifestfile),'parentRuntimeMetadata':str(metadata),
        'parentAcceptancePath':str(acceptance_path),'parentAcceptanceSha256':sha(acceptance_path)}
    v1file=Q/'legacy-policy.private.json';save(v1file,policy);v1sha=sha(v1file)
    assert platform.inspect_parent(v1file,expected_policy_sha256=v1sha)['parentRuntime']==pa
    active['parent']=pb;replace_fixture(metadata,{'state':'running','pid':pb['pid']})
    replace_fixture(acceptance_path,accepted(pb,'not-v1-policy-bound','v1'))
    assert held(lambda:platform.inspect_parent(v1file,expected_policy_sha256=v1sha))
    assert sha(v1file)==v1sha # Original v1 strict pin is NOT weakened.
    v2={k:v for k,v in policy.items() if k not in ('parentAcceptancePath','parentAcceptanceSha256')}
    v2.update(schema='lax-windows-room-parent-policy/v2',parentAcceptanceLocator={'path':str(acceptance_path)})
    v2file=Q/'stable-policy.private.json';save(v2file,v2);policy_sha=sha(v2file)
    parent_config={'authorityId':authority,'hostId':host,'agentId':parent_id,'nativeThreadId':'SYNTHETIC-ORIGINAL-PARENT',
        'state':str(Q/'parent-state'),'codexHome':manifest['codexHome'],'nativeServer':{'manifest':str(manifestfile)},
        'roomOriginPolicy':{'path':str(v2file),'sha256':policy_sha}}
    configfile=Q/'parent-config.private.json';save(configfile,parent_config);config_sha=sha(configfile)
    # First accepted synthetic parent A, then the same policy/config after B.
    active['parent']=pa;replace_fixture(metadata,{'state':'running','pid':pa['pid']})
    replace_fixture(acceptance_path,accepted(pa,policy_sha))
    assert platform.inspect_parent(v2file,expected_policy_sha256=policy_sha)['parentRuntime']==pa
    active['parent']=pb;replace_fixture(metadata,{'state':'running','pid':pb['pid']})
    # Stale previous-incarnation receipt stays closed after the simulated restart.
    replace_fixture(acceptance_path,accepted(pa,policy_sha))
    assert held(lambda:platform.inspect_parent(v2file,expected_policy_sha256=policy_sha))
    # Fixture-only explicit owner acceptance of B changes neither policy nor config.
    accepted_b=accepted(pb,policy_sha);replace_fixture(acceptance_path,accepted_b)
    assert platform.inspect_parent(v2file,expected_policy_sha256=policy_sha)['parentRuntime']==pb
    assert sha(v2file)==policy_sha and sha(configfile)==config_sha
    negatives=[]
    for name,changed in (
        ('wrong-policy',{**accepted_b,'policySha256':'0'*64}),
        ('missing-owner-operation',{k:v for k,v in accepted_b.items() if k!='ownerAcceptanceOperationId'}),
        ('startup-evidence',{**accepted_b,'schema':'lax-room-parent-startup/v1','admissionAllowed':False}),
        ('wrong-host',{**accepted_b,'hostId':str(uuid4())}),
        ('stale-parent',accepted(pa,policy_sha)),
        ('closed-admission',{**accepted_b,'admissionAllowed':False})):
        replace_fixture(acceptance_path,changed)
        assert held(lambda:platform.inspect_parent(v2file,expected_policy_sha256=policy_sha));negatives.append(name)
    replace_fixture(acceptance_path,accepted_b)
    ambiguous={**v2,'parentAcceptanceSha256':'0'*64};ambfile=Q/'ambiguous.private.json';save(ambfile,ambiguous)
    assert held(lambda:platform.read_parent_acceptance(ambiguous,expected_policy_sha256=sha(ambfile)))
    unsafe=Q/'unsafe';unsafe.mkdir()
    relocated={**v2,'parentAcceptanceLocator':{'path':str(unsafe/'not-an-owner-record.json')}}
    assert held(lambda:platform.read_parent_acceptance(relocated,expected_policy_sha256=policy_sha))
    platform.process=old_process;platform.native_peer=old_peer
    assert all(sha(S/n)==v['candidateSha256'] for n,v in sources['files'].items())
    result={'passed':True,'sourceEvent':'00b74d8a-773d-4410-b99c-5e6a091e229a','fixtureOnly':True,
        'readInterface':'read_parent_acceptance(policy, *, expected_policy_sha256)',
        'v1OriginalPinRemainsStrict':True,'twoIncarnationsWithStablePolicyAndConfig':True,
        'negativeCases':negatives+['ambiguous-v1-pin','nonprivate-or-relocated-locator'],
        'realApprovalIssued':False,'managerNativeModelOrProcessActions':0,
        'commonFilesChanged':0,'commonLateRestoreOwnedByCpu':True,
        'limits':['All identities, owner records and native/process proofs are explicitly SYNTHETIC.',
            'No owner acceptance was issued for the actual BLD parent; real candidate admission stays false.',
            'Earlier common reload fixture is reference-only; CPU owns stopped/failed/deferred selection.']}
    save(Q/'result.json',result)
    print(json.dumps({'passed':True,'result':str(Q/'result.json'),'sha256':sha(Q/'result.json'),
        'realApprovalIssued':False,'commonFilesChanged':0}))
if __name__=='__main__':asyncio.run(run())
