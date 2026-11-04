"""Real failed common factory/Mac guard -> same-operation successor integration.

CPU private-files/actual Mac validator, fixture process/NSS and native RPC only.
HTTP catalog is synthetic here; real two-PG/HOME transport is qualified separately.
No real native/model, fleet state, credentials or services are used.
"""
import asyncio,hashlib,importlib.util,json,os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from lax_connector import room_origin_factory as factory,room_session_files as sessions
from lax_connector.room_administration import RoomAdministration,FACTORY_TOOL,digest
from lax_connector.room_origin_control import RoomOriginControl
from lax_connector import room_initial_configuration as recovery


async def scenario(case,lose_native=False):
    case.public_spec()
    parent=json.loads((case.b/'parent.private.json').read_text())
    parent.update(runtimeMode='room-conversation',hollywoodUrl='http://127.0.0.1:1',model='declared-model',effort='xhigh')
    case.put(case.b/'parent.private.json',parent)
    case.policy.update(parentConfig=case.pin(case.b/'parent.private.json'),operatingInstructions=[case.pin(case.b/'OPERATIONS.txt')])
    case.put(case.policyfile,case.policy);config={**parent,'roomOriginPolicy':case.pin(case.policyfile)}
    room,node,agent=(case.ids[k] for k in ('originRoomId','hostId','agentId'))
    slot={'room':room,'node':node,'agent':agent,'coordinator':case.owner,'revision':1,'state':'pending','receipt':None}
    base='rooms/'+room+'/environment-agents';writes=[];attached=[];reports_by_id={};lost_report=[False]
    async def request(method,path,body=None):
        if method!='GET':writes.append((path,body))
        if path=='principals/'+case.owner:return {'id':case.owner,'authority':case.ids['authorityId'],'active':True,'kind':'agent','administrator':True}
        if path=='principals/'+agent:return {'name':'Fresh fixture role'}
        if path=='agents/'+agent+'/role':return {'home_room':room,'primary_role':'room-agent','purpose':'fixture only'}
        if path=='placements/'+case.owner:return {'schema':'hollywood-placement/v1','authorityId':config['authorityId'],
            'agentId':case.owner,'hostId':node,'state':'enabled','mayApply':False,'newExecutionAdmitted':False,'drainVerified':False,'placement':{
                'authority':config['authorityId'],'agent':case.owner,'host':node,'revision':1,'generation':1,'enabled':True}}
        if path==base+'/'+node+'/enroll':slot.update(state='enrolled',revision=2)
        if path.startswith('administration/commands/'):
            return reports_by_id[path.removeprefix('administration/commands/')]
        if path==base+'/'+node+'/report':
            slot.update(state=body['state'],revision=slot['revision']+1,receipt=body['receipt'],note=body['note'])
            reports_by_id[body['operationId']]={'schema':'hollywood-administrative-command/v1','authorityId':config['authorityId'],
                'actorId':case.owner,'operationId':body['operationId'],'method':method,'path':path,
                'wireDigest':digest({'method':method,'path':path,'body':body}),
                'acceptedResult':json.loads(json.dumps({'roomId':room,'agents':[slot],'complete':False,'capabilities':{}}))}
            if ':initial-config:' in body['operationId'] and not lost_report[0]:
                lost_report[0]=True;raise ConnectionError('SYNTHETIC accepted successor report ACK lost')
        if path==base or path.endswith('/enroll') or path.endswith('/report'):
            return json.loads(json.dumps({'roomId':room,'agents':[slot],'complete':False,'capabilities':{}}))
        raise AssertionError('Unexpected fixture request '+path)
    supervisor=SimpleNamespace(config=config,attach=lambda r:attached.append(r),reconcile_admission=lambda:None,checkpoint=lambda:None)
    thread='SYNTHETIC-ORIGINAL-PARENT';key=hashlib.sha256((room+'\0'+node+'\0'+agent).encode()).hexdigest()
    control=RoomOriginControl(config=config,request=request,thread=thread,state=case.b/'control',session_supervisor=supervisor)
    state=control.state/key
    def admin():return RoomAdministration(authority=config['authorityId'],agent=case.owner,thread=thread,request=request,state=state,host_config=config,session_supervisor=supervisor)
    real=factory.origin_configuration
    def legacy(*args,**kw):
        # Reproduce ONLY SDK249's omitted creation fields. The ACTUAL maintained
        # platform adapter/validator generates the positive failed-prelaunch result.
        value=real(*args,**kw);value.pop('sandbox');value.pop('approvalPolicy');return value
    with patch.object(factory,'sys',SimpleNamespace(platform='darwin')),patch.object(sessions,'host_policy',sessions.macos_host_policy):
        with patch.object(factory,'origin_configuration',legacy):
            first=await admin().call(FACTORY_TOOL,{'roomId':room},'room-origin:'+key)
        assert slot['state']=='blocked' and slot['revision']==3 and slot['note']==recovery.GUARD
        assert not case.rpc_calls and not attached
        operation=first['operationId'];workflow=next(state.glob('workflow-*.json'));old= json.loads(workflow.read_text())
        assert old['state']=='completed'
        # Model a maintained parent restart. Preserve original policy/spec bytes;
        # current independently selected policy validates the NEW parent incarnation.
        case.processes[101]=None;case.parent={**case.parent,'pid':102,'birth':'parent-maintained-successor'}
        case.processes[102]=case.parent
        current_policy={**case.policy,'parentProcess':case.parent};current_file=case.b/'current-policy.json';case.put(current_file,current_policy)
        config['roomOriginPolicy']=case.pin(current_file)
        later=patch.object(__import__('lax_connector.room_factory_macos',fromlist=['os']).os,'getpid',return_value=102)
        later.start();case.addCleanup(later.stop)
        saved=__import__('lax_connector.journal',fromlist=['saved']).saved
        saved(control.state/(key+'.json'),{'state':'reported','attempts':8,'slot':dict(slot),'result':first})
        directory=Path(config['state'])/'room-origin-factory'/('room-origin-'+agent)
        original=recovery.original(admin(),workflow,old);assert original is not None
        pins=original[2];assert recovery.available(config,state,thread,operation)
        # Unknown intent, existing child state, altered accepted wire and a current
        # explicit restriction are independently held. Fixture-only negative edits
        # are restored byte-exact; no production unknown evidence is removed.
        intent=directory/'native-initialization-intent.json';intent.write_text('{"fixtureUnknown":true}')
        assert not recovery.available(config,state,thread,operation);intent.unlink()
        home=Path(case.policy['agentRoot'])/agent;home.mkdir();assert not recovery.available(config,state,thread,operation);home.rmdir()
        step=state/digest(operation)/'6.json';raw=step.read_bytes();value=json.loads(raw);value['wireDigest']='0'*64;saved(step,value)
        assert not recovery.available(config,state,thread,operation);step.write_bytes(raw)
        config['sandbox']='read-only';assert not recovery.available(config,state,thread,operation);config.pop('sandbox')
        case.thread_lost=lose_native
        catalog={'authorityId':config['authorityId'],'roomAgentInitializations':[dict(slot)]}
        control.observe(catalog);await asyncio.gather(*list(control.active.values()))
        assert recovery.journal_path(state,operation).exists(), {p.name:json.loads(p.read_text()) for p in control.state.glob('*.json')}
        receipt=json.loads(recovery.journal_path(state,operation).read_text())
        assert receipt['state']=='completed',receipt
        assert all(recovery.sha(path)==sha for path,sha in pins.items())
        assert len(attached)==(0 if lose_native else 1) and case.rpc_calls.count('thread/start')==1 and 'turn/start' not in case.rpc_calls
        if lose_native:assert slot['state']=='unknown' and slot['receipt'] is None
        else:
            assert slot['receipt']['nativeThreadId']==case.thread and slot['state']=='provisioning'
            assert attached[0]['parentRuntimePid']==102
        plan=json.loads((directory/'initial-configuration-successor.json').read_text())
        assert json.loads(Path(plan['spec']['path']).read_text())['parentRuntime']['identity']==case.parent
        assert len([p for p,b in writes if p.endswith('/enroll')])==1 # Original prefix was not replayed.
        reports=[b for p,b in writes if p.endswith('/report')]
        assert len(reports)==2 and reports[0]['operationId']==operation+':report'
        assert reports[1]['operationId'].startswith(operation+':initial-config:')
        before=list(case.rpc_calls);case.thread_lost=False
        again=await admin().call('hollywood_admin_reconcile',{'operationId':operation},'unused')
        assert again['operationId']==operation and case.rpc_calls==before and len(writes)==4
        assert not recovery.available(config,state,thread,operation)
        await control.close()
        return {'passed':True,'actualCommonFactoryMacGuardFailureCompleted':True,'originalBlockedSlotRevision':3,
            'sameWorkflowCredentialIdentityNativeOperation':True,'originalProofFilesByteExact':len(pins),
            'explicitImmutableConfigurationSuccessor':True,'distinctMetadataReportStageSameOriginalOperation':True,
            'negativeUnknownIntentExistingStateWireDriftRestrictionHeld':True,
            'currentParentIncarnationReboundFromApprovedPolicy':True,'lostSuccessorReportAckReadNotRepeated':lost_report[0],
            'uncertainNativeReplyHeldWithoutSecondStart':lose_native,
            'syntheticNativeThreadStarts':1,'realNativeCalls':0,'modelCalls':0,'realDarwin':False,
            'limits':'Synthetic catalog/process/NSS/native RPC; real private journals/policy/validator/platform boundary on CPU.'}


def main():
    source=Path(__file__).resolve().parents[1]/'platform_qualification/macos-resident-r03/test_room_factory_macos.py'
    spec=importlib.util.spec_from_file_location('retained_macos_fixture',source);fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
    fixture.ROOT=Path(os.environ['SDK250_MAC_QA']);results=[]
    for lose_native in (False,True):
        case=fixture.ResidentFilesTests();case.setUp()
        try:results.append(asyncio.run(scenario(case,lose_native)))
        finally:case.doCleanups();case.tearDown()
    result={'passed':True,'scenarios':results}
    Path(os.environ['SDK250_MAC_RESULT']).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))


main()
