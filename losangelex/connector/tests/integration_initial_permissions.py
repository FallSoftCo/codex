"""Full common-factory/Mac files boundary on CPU, not a Darwin native proof.

Existing platform fixture supplies synthetic process/NSS and native RPC facts;
policy validation, private files, IPC socket, factory and Mac adapter are REAL.
No manager, production credential, service, model or actual native call occurs.
"""
import asyncio,copy,hashlib,importlib.util,json,os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from lax_connector import room_origin_factory as factory
from lax_connector import room_session_files as sessions


def main():
    source=Path(__file__).resolve().parents[1]/'platform_qualification/macos-resident-r03/test_room_factory_macos.py'
    spec=importlib.util.spec_from_file_location('retained_macos_fixture',source)
    fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
    fixture.ROOT=Path(os.environ['SDK250_MAC_QA'])
    case=fixture.ResidentFilesTests();case.setUp()
    try:
        case.public_spec() # Explicitly synthetic Darwin identity and RPC only.
        parent=json.loads((case.b/'parent.private.json').read_text())
        parent.update(runtimeMode='room-conversation',hollywoodUrl='http://127.0.0.1:1',
                      model='declared-model',effort='xhigh')
        assert 'sandbox' not in parent and 'approvalPolicy' not in parent
        case.put(case.b/'parent.private.json',parent)
        case.policy['parentConfig']=case.pin(case.b/'parent.private.json')
        case.policy['operatingInstructions']=[case.pin(case.b/'OPERATIONS.txt')]
        case.put(case.policyfile,case.policy)
        config={**parent,'roomOriginPolicy':case.pin(case.policyfile)}
        pins={name:(case.b/name).read_bytes() for name in ('parent.private.json','profile/auth.json','manifest.json','owner.json')}
        attached=[];writes=[]
        supervisor=SimpleNamespace(config=config,attach=lambda r:attached.append(r))
        owner=SimpleNamespace(host_config=config,session_supervisor=supervisor)
        room=case.ids['originRoomId'];node=case.ids['hostId'];agent=case.ids['agentId']
        slot={'room':room,'node':node,'agent':agent,'coordinator':case.owner,'revision':1,'state':'enrolled'}
        base='rooms/'+room+'/environment-agents'
        class Transport:
            accepted_writes=False
            async def http(self,method,path,body=None):
                if method!='GET':writes.append((path,body))
                if path==base or path.endswith('/report') or path.endswith('/enroll'):return {'agents':[slot]}
                if path=='agents/'+agent+'/role':return {'home_room':room,'primary_role':'room-agent','purpose':'fixture only'}
                if path=='principals/'+agent:return {'name':'Fresh fixture role'}
                raise AssertionError('Unexpected metadata request '+path)
        transport=Transport();transport.owner=owner
        # Only select the existing Darwin branches. No generic platform adapter,
        # policy result, child validator or files/bootstrap implementation mock.
        with patch.object(factory,'sys',SimpleNamespace(platform='darwin')),patch.object(sessions,'host_policy',sessions.macos_host_policy):
            normalized,_=sessions.host_policy(config)
            assert normalized['initialPermissions']==case.policy['initialPermissions']
            asyncio.run(factory.provision(transport,{'roomId':room},'native-admin:synthetic-original'))
        assert len(attached)==1 and attached[0]['state']=='ready'
        original=Path(config['state'])/'room-origin-factory'/('room-origin-'+agent)/'spec.private.json'
        child=json.loads(original.read_text())['connectorConfig']
        assert {k:child[k] for k in ('sandbox','approvalPolicy')}==case.policy['initialPermissions']
        assert child['model']==parent['model'] and child['effort']==parent['effort']
        assert case.rpc_calls.count('thread/start')==1 and 'turn/start' not in case.rpc_calls
        assert all((case.b/name).read_bytes()==raw for name,raw in pins.items())
        # Exact prior defect: actual unchanged Mac validator rejects omitted
        # explicit fresh permissions BEFORE synthetic native initialization.
        old=copy.deepcopy(child);old.pop('sandbox');old.pop('approvalPolicy')
        before=list(case.rpc_calls)
        try:case.helper().validate_parent(old)
        except fixture.f.Hold as error:assert str(error)=='Fresh declared initial room configuration required'
        else:raise AssertionError('Old invalid initial config was accepted')
        assert case.rpc_calls==before
        for source_config,policy in (({'sandbox':'read-only'},case.policy),({},{}),
                                     ({},{'initialPermissions':{'sandbox':'danger-full-access','approvalPolicy':'on-request'}})):
            try:sessions.approved_initial_permissions(source_config,{},policy)
            except PermissionError:pass
            else:raise AssertionError('Unreviewed/widened initial permissions accepted')
        result={'passed':True,'commonFactoryAndMacPolicyAndPlatformValidator':True,
            'realPrivateFilesAndIpc':True,'syntheticDarwinProcessAndNativeRpc':True,
            'syntheticThreadStarts':case.rpc_calls.count('thread/start'),'realNativeCalls':0,'modelCalls':0,
            'oldInvalidConfigRejectedBeforeNative':True,'warmParentAndAuthBytesUnchanged':True,
            'initialPermissions':normalized['initialPermissions'],
            'fixtureSourceSha256':hashlib.sha256(source.read_bytes()).hexdigest()}
        out=Path(os.environ['SDK250_MAC_RESULT']);out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
    finally:
        case.doCleanups();case.tearDown()


main()
