"""Owner-only release inspection of all resident logical contexts; read-only.

Never initializes/resumes/replays a thread. Unavailable evidence holds release.
The parent native context is still checked by the existing transport probe.
"""
import json,sqlite3
from pathlib import Path
from .runtime_files import private_file,exclusive_lock
from .room_session_files import inspection_policy as host_policy,digest_file


def journal_counts(config):
    root=Path(config['state']);io=root/'conversation-io.sqlite'
    if not io.exists():raise ValueError('Resident logical session has no original I/O journal')
    db=sqlite3.connect(io.as_uri()+'?mode=ro',uri=True)
    try:
        binding=json.loads(db.execute('SELECT value FROM binding WHERE id=1').fetchone()[0])
        if binding!={'authority':config['authorityId'],'agent':config['agentId'],'thread':config['nativeThreadId']}:
            raise ValueError('Original session I/O binding changed')
        counts={'unboundInputs':db.execute('SELECT count(*) FROM input_source WHERE turn IS NULL').fetchone()[0],
            'attemptingPublications':db.execute("SELECT count(*) FROM publication WHERE state='attempting'").fetchone()[0],
            'unsettledOutputs':db.execute("SELECT count(*) FROM output o LEFT JOIN reply_delivery_hold h ON h.item=o.item WHERE o.state='staged' OR (o.state='queued' AND h.item IS NULL)").fetchone()[0]}
    finally:db.close()
    counts['uncertainHandoffs']=0
    for room in config['rooms']:
        file=root/'rooms'/room['roomId']/'receive.sqlite'
        if not file.exists():continue
        db=sqlite3.connect(file.as_uri()+'?mode=ro',uri=True)
        try:counts['uncertainHandoffs']+=db.execute("SELECT count(*) FROM room_input WHERE state IN ('received','handoff')").fetchone()[0]
        finally:db.close()
    return counts


async def inspect_sessions(config,*,rpc_factory=None):
    registry=Path(config['state'])/'room-sessions'
    if not registry.exists():return {'sessions':[],'quiet':True}
    if not config.get('roomOriginPolicy') and any(registry.glob('session-*.json')):
        raise ValueError('Resident session policy unavailable; cannot assume parent-only quiet')
    if config.get('roomOriginPolicy'):host_policy(config)
    locks=[]
    try:
        # Factory work is part of the host release boundary, not a model turn.
        for file in (Path(config['state'])/'room-origin-factory').glob('*.lock'):
            stream=file.open('a');locks.append(stream);exclusive_lock(stream)
        result=[];seen={config['nativeThreadId']}
        from .rpc_shared import SharedAppServer
        factory=rpc_factory or SharedAppServer
        for file in sorted(registry.glob('session-*.json')):
            private_file(file);record=json.loads(file.read_text());p=Path(record['sessionConfigPath']);private_file(p)
            if digest_file(p)!=record['sessionConfigSha256']:raise ValueError('Resident config identity changed')
            c=json.loads(p.read_text())
            if (c['nativeThreadId']!=record['nativeThreadId'] or c['agentId']!=record['agentId'] or
                c['nativeThreadId'] in seen or c['nativeServer']!=config['nativeServer'] or
                c['hostId']!=config['hostId'] or c['authorityId']!=config['authorityId']):
                raise ValueError('Original logical session/native identity differs')
            seen.add(c['nativeThreadId']);counts=journal_counts(c)
            async def no_effect(*_):raise RuntimeError('No native execution callback permitted in release inspection')
            rpc=factory(c,no_effect,no_effect)
            try:
                await rpc.start()
                value=(await rpc.call('thread/read',{'threadId':c['nativeThreadId'],'includeTurns':False}))['thread']
                if value['id']!=c['nativeThreadId'] or value['status']['type'] not in ('idle','notLoaded'):
                    raise ValueError('A resident logical agent is active or unavailable; parent Idle is insufficient')
                if any(counts.values()):raise ValueError('A resident logical agent retains unsettled I/O; inspect exact originals')
                result.append({'agentId':c['agentId'],'threadId':c['nativeThreadId'],'status':value['status']['type'],'journalCounts':counts})
            finally:await rpc.close()
        return {'sessions':result,'quiet':True,'modelCalls':0}
    finally:
        for stream in locks:stream.close()
