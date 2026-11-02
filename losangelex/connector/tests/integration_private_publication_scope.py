"""Real HTTP/PG private-source denial; no grant change or historical replay."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import secrets
from uuid import uuid4

from aiohttp import ClientSession, web
from hollywood_backbone.store import Store
from hollywood_backbone.server import application
from lax_connector.conversation_io import ConversationIO
from lax_connector.errors import HttpFailure
from lax_connector.room_output import RoomOutput
from lax_connector.room_tools import RoomTools


async def main():
    os.umask(0o077)
    root = Path(os.environ['PUBLICATION_SCOPE_EVIDENCE'])
    root.mkdir(mode=0o700)
    uid = lambda: str(uuid4())
    authority, room = uid(), uid()
    credentials = {name: {'principalId': uid(), 'token': secrets.token_urlsafe(40)}
                   for name in ('Owner', 'Global')}
    store = Store(json.loads(Path(os.environ['ROOM_NATIVE_DATABASE']).read_text()))
    store.migrate()
    store.bootstrap(authority, 'Isolated private publication QA',
                    {'globalRoomId': room, 'credentials': credentials})
    owner, agent = [credentials[name]['principalId'] for name in ('Owner', 'Global')]
    original = store.post(owner, room, 'private-original', {
        'kind': 'message', 'body': 'Synthetic original private source',
        'audience': 'direct', 'recipientId': agent})['event']
    runner = web.AppRunner(application(store), access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    base = 'http://127.0.0.1:' + str(site._server.sockets[0].getsockname()[1]) + '/hollywood/v3/'
    io = ConversationIO(root / 'conversation-io.sqlite', authority=authority,
                        agent=agent, thread='synthetic-original-thread')
    trace = []
    try:
        async with ClientSession(headers={'Authorization': 'Bearer ' + credentials['Global']['token']}) as session:
            async def request(method, path, payload=None):
                trace.append({'method': method, 'path': path})
                async with session.request(method, base + path, json=payload) as response:
                    value = await response.json()
                    if response.status != 200:
                        raise HttpFailure(response.status, str(value))
                    return value
            bad_operation = 'native-room:' + uid()
            bad = {'operationId': bad_operation, 'kind': 'message', 'body': 'Obsolete synthetic hold',
                   'audience': 'room', 'recipientId': owner, 'sourceEventId': original['id'],
                   'responsePhase': 'answer'}
            async with session.post(base + 'rooms/' + room + '/messages', json=bad) as response:
                rejected = {'status': response.status, 'response': await response.json()}
                assert response.status == 403, rejected
            (root / 'original-rejected.json').write_text(json.dumps({'payload': bad, **rejected}, indent=2))
            async with session.get(base + 'commands/' + bad_operation) as response:
                # This API deliberately returns denied, NOT a not-found oracle.
                command_status = response.status
                assert command_status == 403, await response.text()
            with store.pool.connection() as connection:
                assert connection.execute('SELECT count(*) AS n FROM hb_command WHERE principal=%s AND operation=%s',
                                          (agent, bad_operation)).fetchone()['n'] == 0
            io.stage(original)
            io.bind(original, {'turn': {'id': 'original-completed-turn'}})
            io.final('original-completed-turn', 'original-obsolete-final', 'Obsolete synthetic hold')
            io.ended('original-completed-turn', 'completed')
            tools = RoomTools(authority_id=authority, agent_id=agent, thread_id='synthetic-original-thread',
                              request=request, state=root / 'publications', conversation_io=io)
            # A private peer MESSAGE with no expectsReply remains explicit. This
            # suppression is not evidence of a broken listener or poisoned grant.
            assert original['data']['authorKind'] == 'human'
            peer, peer_token = uid(), secrets.token_urlsafe(40)
            store.principal(owner, peer, 'Synthetic private peer', 'agent', peer_token)
            with store.pool.connection() as connection:
                connection.execute('INSERT INTO hb_membership(authority,room,principal,can_read,can_post,can_request) '
                    'VALUES(%s,%s,%s,true,true,true)', (authority, room, peer))
            private_peer = store.post(peer, room, 'passive-private-source', {
                'kind': 'message', 'body': 'Synthetic finite explicit-publication instruction',
                'audience': 'direct', 'recipientId': agent})['event']
            io.stage(private_peer)
            io.bind(private_peer, {'turn': {'id': 'passive-completed-turn'}})
            io.final('passive-completed-turn', 'passive-final', 'Old held prerequisite')
            io.ended('passive-completed-turn', 'completed')
            row = next(row for row in io.pending() if row['item'] == 'passive-final')
            assert await RoomOutput(io, tools).deliver(row)
            assert io.db.execute('SELECT state,reason FROM output WHERE item=?', ('passive-final',)).fetchone()['state'] == 'suppressed'
            assert trace == []
            # The existing wrong payload is never changed/retried. A distinct
            # current request and semantic publication report the new outcome.
            current = store.post(peer, room, 'new-current-completion-request', {
                'kind': 'request', 'body': 'Qualify existing reader; never create a second key',
                'audience': 'direct', 'recipientId': agent, 'expectsReply': True})['event']
            io.stage(current)
            io.bind(current, {'turn': {'id': 'new-completion-turn'}})
            result = await tools.publish(room, {'body': 'Current synthetic qualification completed',
                'audience': 'direct', 'recipientId': peer, 'sourceEventId': current['id'], 'responsePhase': 'answer'},
                hashlib.sha256(b'new-current-completion-publication').hexdigest(), turn='new-completion-turn')
            assert result['accepted'] and result['event']['audience'] == 'direct'
            assert result['event']['source'] == current['id'] and result['event']['recipient'] == peer
            assert len(trace) == 1 and trace[0]['method'] == 'POST'
            async with session.get(base + 'commands/' + bad_operation) as response:
                assert response.status == 403, await response.text()
            with store.pool.connection() as connection:
                assert connection.execute('SELECT count(*) AS n FROM hb_command WHERE principal=%s AND operation=%s',
                                          (agent, bad_operation)).fetchone()['n'] == 0
            report = {'passed': True, 'authority': authority, 'serverModule': str(__import__(
                'hollywood_backbone.server', fromlist=['__file__']).__file__),
                'privateSourceRoomBroadening': 403, 'originalCommandRemainsAbsent': True,
                'absenceProof': 'Exact own QA principal/operation SQL count zero; denied HTTP alone is not absence proof',
                'commandReadHttpStatus': command_status,
                'passivePeerFinalSuppressedWithoutPost': True, 'newCurrentPrivateAnswerEvent': result['event']['id'],
                'oldRejectedOperationRetried': False, 'oldStaleFinalReopened': False,
                'grantChanges': False, 'nativeModelCalls': 0, 'productionEffects': 0}
            (root / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
            print(json.dumps(report))
    finally:
        io.close()
        await runner.cleanup()
        store.pool.close()


asyncio.run(main())
