"""Reviewed role handover for an existing, drained logical room context.

Run as its existing host account after stopping the parent at a quiet boundary.
The original thread, configuration, registry and native history are retained.
This is an operator operation, never a background room/model polling loop.
"""
import asyncio
import hashlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from .journal import saved
from .runtime_files import exclusive_lock, private_file
from .room_participation import PROJECT_VERSION, project_policy, instructions_digest, loaded
from .room_tools import TOOLS
from .project_tools import PROJECT_TOOLS
from .rpc_shared import native_client
from .rpc import RpcError


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def reviewed_configuration(original, policy, original_sha):
    if (original.get('runtimeMode')!='room-conversation' or not original.get('originRoomId')
            or original.get('rooms')!=[{'roomId':original['originRoomId'],'after':0}]):
        raise ValueError('A single original room-owned logical context is required')
    if (policy.get('version')!=1 or policy.get('mode')!='lead'
            or not isinstance(policy.get('revision'),int) or isinstance(policy['revision'],bool)
            or policy['revision']<1):
        raise ValueError('Canonical lead policy v1 is required')
    binding=dict(version=1,roomId=original['originRoomId'],leadAgentId=str(UUID(policy['leadAgentId'])),revision=policy['revision'])
    result={**original,'projectCommunication':binding,'conversationParticipationPolicy':PROJECT_VERSION,
            'conversationDynamicTools':TOOLS+PROJECT_TOOLS}
    before=original.get('conversationResumeInstructions',{})
    if not before.get('baseInstructions'):
        raise ValueError('Preserve the actual original base and developer instructions')
    result['conversationResumeInstructions']={**before,'baseInstructions':project_policy(before['baseInstructions'],result)}
    result['instructions']=project_policy(original['instructions'],result)
    result['conversationInstructionAdoptionId']=digest(dict(authority=original['authorityId'],agent=original['agentId'],
        thread=original['nativeThreadId'],originalConfigurationSha256=original_sha,project=binding,
        instructions=instructions_digest(result['conversationResumeInstructions'])))
    return result


def require_settled(state):
    """Do not turn unknown input or publication into permission to drop it."""
    receives=list(state.rglob('receive.sqlite'))
    if len(receives)>64:raise ValueError('Incomplete original receive inventory')
    for file in receives:
        private_file(file)
        with sqlite3.connect(file.as_uri()+'?mode=ro',uri=True) as db:
            if db.execute("SELECT 1 FROM room_input WHERE state!='committed' LIMIT 1").fetchone():
                raise ValueError('Original room input needs reconciliation before role handover')
    file=state/'conversation-io.sqlite'
    if file.exists():
        private_file(file)
        with sqlite3.connect(file.as_uri()+'?mode=ro',uri=True) as db:
            if db.execute("SELECT 1 FROM output WHERE state IN ('staged','queued','blocked') LIMIT 1").fetchone():
                raise ValueError('Original native output needs reconciliation before role handover')
            if db.execute("SELECT 1 FROM publication WHERE state NOT IN ('accepted','rejected') LIMIT 1").fetchone():
                raise ValueError('Original publication receipt needs reconciliation before role handover')
    # Explicit tool publications can be unknown even without a normal final.
    # Keep their original journals; a role change is never delivery evidence.
    for index,file in enumerate((state/'publications').glob('*.json')):
        if index>=10000:raise ValueError('Original publication inventory needs a bounded retained index')
        private_file(file)
        if file.stat().st_size>262144:raise ValueError('Original publication exceeds reviewed metadata bound')
        row=json.loads(file.read_text())
        if row.get('state')not in ('accepted','rejected','reconsider'):
            raise ValueError('Original explicit publication remains uncertain; reconcile its original command')


class RoleHandoverPending(ValueError):
    """The original logical session is held by its recorded role transition."""


def role_receipt(record):
    if record.get('roleAdoptionIntent'):
        raise RoleHandoverPending('Original role handover is awaiting reconciliation; no old context resumed')
    path=record.get('roleAdoptionReceipt')
    if not path:return None
    private_file(Path(path));value=json.loads(Path(path).read_text())
    if (value.get('schema')!='lax-project-role-adoption/v1' or value.get('state')!='accepted'
            or value['receipt']['newRecord']!=record):
        raise RoleHandoverPending('Original role handover acceptance is incomplete')
    expected=reviewed_configuration(value['originalConfig'],value['policy'],value['originalConfigSha256'])
    file=Path(record['sessionConfigPath']);private_file(file)
    if (hashlib.sha256(file.read_bytes()).hexdigest()!=record['sessionConfigSha256']
            or json.loads(file.read_text())!=expected):
        raise ValueError('Accepted role configuration differs from its reviewed successor')
    return value


def accepts_initialization(original, current):
    """An immutable bootstrap receipt may name an accepted older config file."""
    keys=('agentId','originRoomId','nativeThreadId','sessionConfigPath','sessionConfigSha256')
    wanted={k:original[k]for k in keys};seen=set()
    for _ in range(16):
        role_receipt(current)
        if {k:current[k]for k in keys}==wanted:return True
        if any(current[k]!=wanted[k]for k in keys[:3]):return False
        pointer=current.get('roleAdoptionReceipt')
        if not pointer or pointer in seen:return False
        seen.add(pointer);current=json.loads(Path(pointer).read_text())['originalRecord']
    raise ValueError('Role successor history needs a bounded index')


async def cold(rpc, thread, *, reviewed_instructions=None, native_config=None):
    """Use native idle-cache reconfiguration, never archive or a daemon reset.

    Unsubscribe alone retains a native cache for its configured grace period.
    At an unsubscribed idle boundary native resume can apply the actual reviewed
    instructions and a zero cache-retention delay. No model runs between these
    metadata operations; the normal runtime later restores its ordinary config.
    """
    result=await rpc.call('thread/read',{'threadId':thread,'includeTurns':False})
    if result['thread']['id']!=thread:raise ValueError('Native thread identity changed')
    status=result['thread']['status']['type']
    if status=='notLoaded':return
    if status!='idle':raise ValueError('Original native context is not idle: '+status)
    cursor=None
    while True:
        terminals=await rpc.call('thread/backgroundTerminals/list',{'threadId':thread,'limit':100,**({'cursor':cursor}if cursor else {})})
        if terminals.get('data') or terminals.get('terminals'):
            raise ValueError('Original background commands must settle; none were stopped')
        if not any(k in terminals for k in ('data','terminals')):raise ValueError('Native background-command inventory is unavailable')
        following=terminals.get('nextCursor')
        if not following:break
        if following==cursor:raise ValueError('Native background-command inventory is incomplete')
        cursor=following
    closed=asyncio.Event();original_event=rpc.on_event
    async def event(method,params):
        await original_event(method,params)
        if params.get('threadId')==thread and (method=='thread/closed' or method=='thread/status/changed' and params.get('status',{}).get('type')=='notLoaded'):
            closed.set()
    rpc.on_event=event
    try:
        await rpc.call('thread/unsubscribe',{'threadId':thread})
        if not await loaded(rpc,thread):return
        if not reviewed_instructions or not reviewed_instructions.get('baseInstructions'):
            raise ValueError('Original native idle cache requires the actual reviewed role instructions; no fake setting or archive fallback')
        # Do not send new declarations while the old cache is loaded. Native
        # applies the real instruction change only without subscribers/activity.
        try:
            await rpc.call('thread/resume',{'threadId':thread,'excludeTurns':True,**reviewed_instructions,
                'config':{**(native_config or {}),'thread_unload_delay_secs':0}})
        except RpcError as error:
            if error.code!=-32600:raise
            # A native invalid-request response can race its original close.
            # Its code/message does not establish release: confirm the actual
            # original thread is not loaded, otherwise preserve the rejection.
            try:await asyncio.wait_for(closed.wait(),10)
            except asyncio.TimeoutError:pass
            if not await loaded(rpc,thread):return
            raise
        closed.clear()
        await rpc.call('thread/unsubscribe',{'threadId':thread})
        if not await loaded(rpc,thread):return
        try:await asyncio.wait_for(closed.wait(),5)
        except asyncio.TimeoutError:pass
        if await loaded(rpc,thread):
            raise ValueError('Reviewed idle-cache release is unconfirmed; preserve the original handover')
    finally:rpc.on_event=original_event


async def checkpoint(rpc, config, state, snapshot, operation, *, reviewed_instructions=None, native_config=None):
    """No-summary native checkpoint; no human input or model inference."""
    await cold(rpc,config['nativeThreadId'],reviewed_instructions=reviewed_instructions,native_config=native_config)
    await rpc.call('thread/resume',{'threadId':config['nativeThreadId'],'excludeTurns':True,
        'config':{**(native_config or {}),'features.token_budget':True,'thread_unload_delay_secs':0},'dynamicTools':config.get('conversationDynamicTools',TOOLS)})
    from .native_context_rebuild import install
    runner=SimpleNamespace(rpc=rpc,thread=config['nativeThreadId'],state=state,
        trace=lambda name,value:saved(state/(name+'.json'),value))
    receipt=await install(runner,snapshot,operation)
    await cold(rpc,config['nativeThreadId'],reviewed_instructions=reviewed_instructions,native_config=native_config)
    return receipt


async def adopt(parent_path, agent, expected_config_sha, expected_record_sha, policy, seed, operation, *, work=()):
    """Write a reviewed immutable configuration, then atomically switch its pointer.

    Before native changes the registry durably holds the logical agent. Neither
    an old nor a new runtime may load it through a partially completed handover.
    Original initialization/configuration/history files are never rewritten.
    """
    if not isinstance(seed,str) or not seed.strip() or len(seed.encode())>4096:
        raise ValueError('Use a reviewed bounded handover seed, not the old transcript')
    if not isinstance(work,(tuple,list)) or len(work)>50:
        raise ValueError('Use a bounded explicitly reviewed original-work manifest')
    for item in work:
        if (not isinstance(item,dict) or set(item)!={'eventId','canonicalSha256','state','reason'}
                or item['state']not in ('ready','paused','cancelled','complete','fault')
                or not isinstance(item['reason'],str) or not item['reason'].strip()
                or len(item['reason'].encode())>2048):
            raise ValueError('Each retained work item needs canonical identity/hash and an explicit disposition')
        UUID(item['eventId'])
    if len({v['eventId']for v in work})!=len(work):raise ValueError('Duplicate original work in handover')
    parent_path=Path(parent_path);private_file(parent_path)
    parent=json.loads(parent_path.read_text());agent=str(UUID(agent))
    registry=Path(parent['state'])/'room-sessions'/('session-'+agent+'.json');private_file(registry)
    parent_lock=(Path(parent['state'])/'connector.lock').open('a');child_lock=None;rpc=None
    try:
        exclusive_lock(parent_lock)
        observed=json.loads(registry.read_text());observed_config=Path(observed['sessionConfigPath']);private_file(observed_config)
        state=Path(json.loads(observed_config.read_text())['state'])
        child_lock=(state/'connector.lock').open('a');exclusive_lock(child_lock)
        status=json.loads((Path(parent['state'])/'room-sessions'/'status.private.json').read_text())
        if 'project-role-handover/v1' not in status.get('runtimeCapabilities',[]):
            raise ValueError('Install the role-aware parent runtime before changing logical role pointers')
        policy_ref={k:policy[k]for k in ('version','mode','leadAgentId','revision','inputAfterSeq')}
        identity=digest(dict(operation=operation,original=expected_config_sha,record=expected_record_sha,
            policy=policy_ref,seedSha256=hashlib.sha256(seed.encode()).hexdigest(),work=work))
        root=state/'project-adoptions';root.mkdir(mode=0o700,exist_ok=True);journal=root/(identity+'.json')
        prior=json.loads(journal.read_text())if journal.exists()else None
        if prior and prior['state']=='accepted':
            role_receipt(observed)
            if observed!=prior['receipt']['newRecord']:raise ValueError('Accepted role pointer subsequently changed')
            return prior['receipt']
        if observed.get('roleAdoptionIntent') and observed['roleAdoptionIntent']!=str(journal):
            raise RoleHandoverPending('A different original role handover already owns this logical session')
        original_record=prior['originalRecord']if prior else observed
        config_path=Path(original_record['sessionConfigPath']);private_file(config_path)
        original=json.loads(config_path.read_text())
        if (hashlib.sha256(config_path.read_bytes()).hexdigest()!=expected_config_sha
                or digest(original_record)!=(prior['originalRecordDigest']if prior else digest(observed))):
            raise ValueError('Reviewed original logical binding changed')
        from .room_session_supervisor import RoomSessionSupervisor
        supervisor=RoomSessionSupervisor(SimpleNamespace(config=parent,thread=parent['nativeThreadId']))
        supervisor._validate(original_record)
        if not prior and hashlib.sha256(registry.read_bytes()).hexdigest()!=expected_record_sha:
            raise ValueError('Reviewed original registry CAS changed')
        from aiohttp import ClientSession,ClientTimeout
        headers={'Authorization':'Bearer '+original['token'],'X-Hollywood-Authority':original['authorityId'],'X-Hollywood-Agent':agent}
        async with ClientSession(timeout=ClientTimeout(total=15))as session:
            async with session.get(original['hollywoodUrl'].rstrip('/')+'/hollywood/v3/rooms/'+original['originRoomId'],headers=headers)as response:
                if response.status!=200:raise ValueError('Canonical lead-policy read is unavailable')
                value=await response.json()
            originals=[]
            for item in work:
                async with session.get(original['hollywoodUrl'].rstrip('/')+'/hollywood/v3/inbox/events/'+item['eventId'],headers=headers)as response:
                    if response.status!=200:raise ValueError('Original work is not canonically readable; do not substitute another request')
                    observed_work=(await response.json()).get('event')
                if (not isinstance(observed_work,dict) or observed_work.get('id')!=item['eventId']
                        or observed_work.get('room')!=original['originRoomId']
                        or observed_work.get('authority')!=original['authorityId']
                        or observed_work.get('data',{}).get('authorKind')!='human'
                        or digest(observed_work)!=item['canonicalSha256']):
                    raise ValueError('Reviewed canonical original work changed')
                if agent!=policy_ref['leadAgentId']:raise ValueError('Only the project lead inherits human obligations')
                originals.append({**item,'event':observed_work})
        actual=value.get('room',{}).get('leadPolicy',{})
        if (value.get('authorityId')!=original['authorityId'] or value.get('room',{}).get('id')!=original['originRoomId']
                or any(actual.get(k)!=policy_ref[k]for k in policy_ref)):
            raise ValueError('Canonical room role differs from reviewed handover')
        require_settled(state)
        updated=reviewed_configuration(original,actual,expected_config_sha)
        successor=config_path.with_name('session-config-project-'+identity+'.private.json')
        if successor.exists():
            private_file(successor)
            if json.loads(successor.read_text())!=updated:raise ValueError('Original immutable role successor changed')
        else:saved(successor,updated)
        new_record={**original_record,'sessionConfigPath':str(successor),
            'sessionConfigSha256':hashlib.sha256(successor.read_bytes()).hexdigest(),'roleAdoptionReceipt':str(journal)}
        new_record.pop('roleAdoptionIntent',None)
        held_record={**new_record,'roleAdoptionIntent':str(journal)};held_record.pop('roleAdoptionReceipt',None)
        base=dict(schema='lax-project-role-adoption/v1',operation=operation,originalConfig=original,originalRecord=original_record,
            originalConfigSha256=expected_config_sha,originalRecordSha256=expected_record_sha,originalRecordDigest=digest(original_record),
            policy=policy_ref,seed=seed,work=work,newRecord=new_record)
        if not prior:
            saved(journal,{**base,'state':'prepared'})
            saved(registry,held_record) # write-ahead hold before any native operation
        elif observed not in (held_record,new_record):raise ValueError('Original handover registry pointer changed')
        if prior and prior['state']!='checkpoint_accepted':
            raise RoleHandoverPending('Inspect the original native checkpoint before resuming this handover; never repeat it')
        async def event(method,params):pass
        async def no_tools(*args):raise RuntimeError('Handover cannot execute model tools or approvals')
        rpc=native_client(original,event,no_tools);await rpc.start()
        if prior:
            receipt=prior['checkpoint']
            await cold(rpc,original['nativeThreadId'],reviewed_instructions=updated['conversationResumeInstructions'])
        else:
            content=json.dumps(dict(schema='lax-project-handover/v1',roomId=original['originRoomId'],
                role='lead'if agent==policy['leadAgentId']else'worker',seed=seed,
                meaning='Retained evidence only; not new human input or authority to replay effects.'),sort_keys=True,separators=(',',':'))
            snapshot=dict(sha256=hashlib.sha256(content.encode()).hexdigest(),totalBytes=len(content.encode()),chunks=[dict(offset=0,content=content)])
            receipt=await checkpoint(rpc,original,state,snapshot,'project-handover:'+identity,reviewed_instructions=updated['conversationResumeInstructions'])
            saved(journal,{**base,'state':'checkpoint_accepted','checkpoint':receipt})
        # Import before publishing the role pointer. This is retained work, not
        # turn/start or a second human POST; only explicit ready dispositions
        # queue a deduplicated wake referencing that same accepted source.
        from .lead_work import LeadWork
        ledger=LeadWork(state/'project-work.sqlite',authority=original['authorityId'],room=original['originRoomId'],agent=agent,lead=policy_ref['leadAgentId'])
        try:
            imported=[dict(eventId=item['eventId'],workId=ledger.adopt_original(item['event'],item['state'],item['reason']),state=item['state'])for item in originals]
        finally:ledger.close()
        # A single atomic registry pointer publishes the immutable config. Both
        # pending forms remain held until the accepted receipt is durable.
        if json.loads(registry.read_text())not in(held_record,new_record):raise ValueError('Original role pointer changed during native handover')
        saved(registry,new_record)
        result=dict(state='accepted',agentId=agent,roomId=original['originRoomId'],nativeThreadId=original['nativeThreadId'],
            policyRevision=policy['revision'],newRecord=new_record,contextCheckpoint=receipt,
            originalConfigurationSha256=expected_config_sha,modelsStarted=0,servicesStarted=0,originalInputReplayed=False,retainedWork=imported)
        saved(journal,{**base,'state':'accepted','receipt':result,'checkpoint':receipt})
        return result
    finally:
        if rpc:await rpc.close()
        if child_lock:child_lock.close()
        parent_lock.close()


def main():
    """Apply one private reviewed handover plan, not a model-facing mutation."""
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',required=True,type=Path)
    parser.add_argument('--receipt',required=True,type=Path)
    args=parser.parse_args();private_file(args.plan)
    plan=json.loads(args.plan.read_text())
    keys={'parentPath','agent','expectedConfigSha256','expectedRecordSha256','policy','seed','operation','work'}
    if set(plan)!=keys:raise ValueError('Use the exact reviewed original-binding handover fields')
    result=asyncio.run(adopt(plan['parentPath'],plan['agent'],plan['expectedConfigSha256'],plan['expectedRecordSha256'],
        plan['policy'],plan['seed'],plan['operation'],work=plan['work']))
    if args.receipt.exists():
        private_file(args.receipt)
        if json.loads(args.receipt.read_text())!=result:raise ValueError('Original operator receipt differs')
    else:saved(args.receipt,result)
    print(json.dumps({k:result[k]for k in ('state','agentId','roomId','nativeThreadId','policyRevision','modelsStarted','originalInputReplayed')}))

if __name__=='__main__':main()
