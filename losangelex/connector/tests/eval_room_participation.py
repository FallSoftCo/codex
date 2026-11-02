"""Four frozen real-model replays; all effect tools are callback stubs.

Uses new ephemeral QA contexts on the EXISTING shared native daemon/account.
Never starts a server, enrolls an agent, sends Hollywood HTTP or executes a
model-selected command. An effective tool ceiling is verified before sampling.
"""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import time
from uuid import uuid4

from lax_connector.journal import saved
from lax_connector.rpc_shared import SharedAppServer
from lax_connector.room_tools import TOOLS, definition


LOCAL = definition('fixture_local_inspect',
    'Read-only local host process/filesystem/storage command. The qualification '
    'transport returns frozen host facts instead of executing the command.',
    {'command': {'type': 'string'}}, ['command'])


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def snapshot(config):
    info = Path('/proc/392451').stat()
    image = Path('/proc/392451/exe').stat()
    return {'nativePid': 392451, 'processIdentity': [info.st_ino, info.st_ctime_ns],
            'imageIdentity': [image.st_dev, image.st_ino, image.st_size, image.st_ctime_ns],
            'originalConfigSha256': sha(config)}


async def trial(root, config, protocol, events, arm, case):
    out = root / (arm + '-' + case)
    out.mkdir(mode=0o700)
    (out / 'work').mkdir(mode=0o700)
    current = events[1] if case == 'shared-human-continue' else events[2]
    tools = [*TOOLS, LOCAL]
    ceiling = {'allowedTools': [{'name': item['name']} for item in tools]
               + [{'name': 'exec'}, {'name': 'wait'}]}
    terminal = asyncio.Queue()
    calls, finals, public_events = [], [], []
    turn = None
    ended = False
    scope = {**config, 'state': str(out)}
    scope.pop('nativeThreadId', None)  # New ephemeral QA, never bind the Global.
    saved(out / 'intent.json', {'arm': arm, 'case': case, 'protocolSha256': sha(root / 'protocol.json'),
          'runnerSha256': sha(__file__), 'sharedNativePid': 392451, 'effects': 'stubbed',
          'model': protocol['model'], 'effort': protocol['effort'], 'currentSource': current['id']})

    async def event(method, params):
        if method == 'item/completed' and params.get('item', {}).get('type') == 'agentMessage':
            item = params['item']
            if item.get('phase') in (None, 'final_answer'):
                finals.append({'id': item['id'], 'text': item.get('text', ''), 'phase': item.get('phase')})
        if method in ('turn/started', 'turn/completed', 'error', 'thread/tokenUsage/updated'):
            public_events.append({'method': method, 'params': params})
        if method == 'turn/completed':
            await terminal.put(params['turn'])

    async def callback(method, params):
        if method != 'item/tool/call':
            raise RuntimeError('QA did not authorize approval or other native callbacks')
        arguments = params['arguments']
        if isinstance(arguments, str):
            arguments = json.loads(arguments)
        call = {'tool': params['tool'], 'arguments': arguments, 'callId': params['callId']}
        calls.append(call)
        saved(out / 'tool-calls.json', calls)
        if len(calls) > protocol['maximumStubCallsPerTurn']:
            if turn:
                asyncio.create_task(rpc.call('turn/interrupt', {'threadId': rpc.thread_id, 'turnId': turn}))
            raise RuntimeError('Frozen QA tool-call bound exceeded')
        name = params['tool']
        if name == 'fixture_local_inspect':
            value = {'hostname': 'ozzz-aosp', 'readOnlyFixture': True,
                     'availableBytes': 972390445056, 'cpuFloorBytes': 8589934592,
                     'source': 'Frozen host-management metadata; not a fresh production check',
                     'reloadEvidence': 'Naturally required reload sample found fstab-generator waiting on FUSE metadata; full duration attribution unproved',
                     'cleanup': 'No owner-released disposable target in this bounded inventory',
                     'guide': '/var/lib/lax-host-resources/cpu-20261102-r01/AGENT-RESOURCE-GUIDE.txt'}
        elif name == 'hollywood_publish':
            value = {'accepted': True, 'event': {'id': str(uuid4()), 'room': arguments['roomId'],
                     'recipient': arguments.get('recipientId'), 'source': arguments.get('sourceEventId')},
                     'deliveries': [], 'stubbedEffect': True}
        elif name in {'hollywood_context', 'hollywood_room_info'}:
            value = {'authorityId': config['authorityId'], 'room': {'id': current['room']},
                     'self': {'agentId': config['agentId'], 'host': 'ozzz-aosp'},
                     'actors': [{'id': identity, 'name': name} for identity, name in (
                         (config['agentId'], 'CPU Global'),
                         ('6d92b00b-a083-4e1a-a57f-bd51f4e1d44e', 'GPU Global'),
                         ('73cefa47-44e5-59cb-b3ec-9a5a326bcfa9', 'Mac VM Global'),
                         ('6b453a5d-44f0-593c-8e91-05b248e4f19c', 'Native Mac Global'),
                         ('9595c782-22f7-514c-9c70-7d5bdffe4370', 'system76 Global'),
                         ('a3ac9ccf-dd59-5e5c-b827-3250d19b31d0', 'Windows Global'))]}
        elif name == 'hollywood_read_room':
            value = {'authorityId': config['authorityId'], 'roomId': current['room'],
                     'events': events[:2] if case == 'shared-human-continue' else [current],
                     'nextCursor': current['seq']}
        else:
            value = {'accepted': False, 'stubbedEffect': True,
                     'error': 'No administrative or new-identity action is authorized in this fixture'}
        return {'success': True, 'contentItems': [{'type': 'inputText', 'text': json.dumps(value)}]}

    rpc = SharedAppServer(scope, event, callback)
    try:
        await rpc.start()
        created = await rpc.call('thread/start', {
            'model': protocol['model'], 'cwd': str(out / 'work'), 'ephemeral': True,
            'baseInstructions': (root / (arm + '-instructions.txt')).read_text(),
            'developerInstructions': 'Qualification replay on CPU. Effects are stubbed. '
                'Only the provided dynamic effect tools are available; do not claim live deployment. '
                'Use the ordinary role/task contract for the replay, not a verbal prediction of what an agent would do.',
            'dynamicTools': tools, 'toolPolicy': ceiling,
            'sandbox': 'read-only', 'approvalPolicy': 'never',
            'config': {'model_reasoning_effort': protocol['effort'], 'features.shell_tool': False,
                       'project_doc_max_bytes': 0, 'thread_unload_delay_secs': 0}})
        effective = {(item.get('namespace') or 'functions', item['name'])
                     for item in created.get('toolPolicy', {}).get('allowedTools', [])}
        expected = {('functions', item['name']) for item in ceiling['allowedTools']}
        if effective != expected:
            raise RuntimeError('Effective native effect ceiling was not verified; NO model submission')
        saved(out / 'thread.json', {'threadId': rpc.thread_id, 'ephemeral': created['thread']['ephemeral'],
                                  'effectiveToolPolicy': created['toolPolicy'], 'model': created['model']})
        assert created['model'] == protocol['model'] and created['thread']['ephemeral'] is True
        context = {'selfHost': 'ozzz-aosp', 'selfAgent': config['agentId'],
                   'currentLocalOwnership': 'CPU storage/mount architecture, reload diagnosis, fleet source integration',
                   'otherOwners': 'Existing GPU/Mac/VM/system76/Windows Globals each own their local inspection; all receive public human input directly',
                   'history': events[:1] if case == 'shared-human-continue' else [],
                   'currentEvent': current}
        started = await rpc.call('turn/start', {'threadId': rpc.thread_id,
            'clientUserMessageId': str(uuid4()),
            'input': [{'type': 'text', 'text': json.dumps(context), 'text_elements': []}]})
        turn = started['turn']['id']
        saved(out / 'turn.json', {'threadId': rpc.thread_id, 'turnId': turn})
        result = await asyncio.wait_for(terminal.get(), protocol['secondsPerTurn'])
        ended = True
        saved(out / 'result.json', {'nativeThreadId': rpc.thread_id, 'nativeTurn': result,
             'calls': calls, 'finals': finals, 'events': public_events, 'effects': 'stubbed',
             'nativeModelSampled': True, 'noSemanticScoreYet': True})
    except Exception as error:
        saved(out / 'failure.json', {'type': type(error).__name__, 'error': str(error)[:1000],
             'threadId': rpc.thread_id, 'turnId': turn, 'calls': calls, 'finals': finals})
        raise
    finally:
        if turn and not ended:
            await rpc.call('turn/interrupt', {'threadId': rpc.thread_id, 'turnId': turn})
            await asyncio.wait_for(terminal.get(), 30)
        if rpc.thread_id:
            saved(out / 'unsubscribe.json', await rpc.call('thread/unsubscribe', {'threadId': rpc.thread_id}))
        await rpc.close()


async def main():
    root = Path(os.environ['PARTICIPATION_EVIDENCE'])
    protocol = json.loads((root / 'protocol.json').read_text())
    config_file = Path(os.environ['PARTICIPATION_ORIGINAL_CONFIG'])
    config = json.loads(config_file.read_text())
    for name, expected in protocol['files'].items():
        assert sha(root / name) == expected
    assert config['model'] == protocol['model'] and config['effort'] == protocol['effort']
    events = json.loads((root / 'traffic.json').read_text())
    before = snapshot(config_file)
    assert not (root / 'model-execution-intent.json').exists()
    saved(root / 'model-execution-intent.json', {'protocolSha256': sha(root / 'protocol.json'),
          'runnerSha256': sha(__file__), 'before': before, 'maximumModelTurns': 4})
    results = []
    # Deliberately sequential (<=2 admitted); no callbacks from another cell
    # can be mistaken for this trial's effect. No rerun on a failed cell.
    for case in protocol['cases']:
        for arm in protocol['arms']:
            try:
                await trial(root, config, protocol, events, arm, case)
                results.append({'case': case, 'arm': arm, 'completedTransport': True})
            except Exception as error:
                results.append({'case': case, 'arm': arm, 'completedTransport': False, 'errorType': type(error).__name__})
    after = snapshot(config_file)
    saved(root / 'execution-result.json', {'cells': results, 'originalIdentitiesUnchanged': before == after,
          'before': before, 'after': after, 'semanticScore': 'not yet reviewed', 'at': time.time()})


asyncio.run(main())
