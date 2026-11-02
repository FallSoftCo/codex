"""Actual zero-model, same-thread cold instruction adoption on the shared daemon.

Creates only one named private QA context (no Hollywood agent). Releases and
archives ONLY that context; never restarts native or touches a product thread.
"""
import asyncio
import hashlib
import json
import os
from pathlib import Path

from lax_connector.journal import saved
from lax_connector.room_participation import VERSION, PRIVATE_FINAL_LEGACY, resume_overrides, require_cold_boundary, instructions_digest
from lax_connector.room_instruction_adoption import InstructionAdoption
from lax_connector.rpc_shared import SharedAppServer


async def main():
    os.umask(0o077)
    root = Path(os.environ['PARTICIPATION_ADOPTION_EVIDENCE'])
    root.mkdir(mode=0o700)
    original = json.loads(Path(os.environ['PARTICIPATION_ORIGINAL_CONFIG']).read_text())
    turns = []
    initial = 'QA ONLY original owner role. ' + PRIVATE_FINAL_LEGACY
    image = Path('/proc/392451/exe').stat()

    async def event(method, params):
        if method == 'turn/started':
            turns.append(params)

    async def unsupported(*args):
        raise AssertionError('No model/tool/approval callback authorized')

    def client(revision, thread=None):
        state = root / revision
        state.mkdir(mode=0o700)
        config = {**original, 'state': str(state)}
        config.pop('nativeThreadId', None)
        if thread:
            config['nativeThreadId'] = thread
        return SharedAppServer(config, event, unsupported)

    rpc = client('initial')
    try:
        await rpc.start()
        created = await rpc.call('thread/start', {'cwd': str(root), 'model': original['model'],
            'baseInstructions': initial, 'dynamicTools': [], 'toolPolicy': {'allowedTools': []},
            'sandbox': 'read-only', 'approvalPolicy': 'never', 'historyMode': 'legacy',
            'config': {'features.shell_tool': False, 'thread_unload_delay_secs': 0,
                       'project_doc_max_bytes': 0, 'model_reasoning_effort': original['effort']}})
        thread = created['thread']['id']
        saved(root / 'original.json', {'threadId': thread, 'baseInstructions': initial,
              'originalToolPolicy': created['toolPolicy'], 'model': created['model'],
              'approvalPolicy': created['approvalPolicy'], 'sandbox': created['sandbox']})
        await rpc.call('thread/name/set', {'threadId': thread, 'name': 'QA direct room instruction adoption; zero-model'})
        # Only QA preferences are persisted, not any original product choice.
        await rpc.call('thread/settings/update', {'threadId': thread, 'model': original['model'],
            'effort': original['effort'], 'approvalPolicy': created['approvalPolicy'], 'sandboxPolicy': created['sandbox']})
        try:
            await require_cold_boundary(rpc, thread)
        except ValueError:
            loaded_held = True
        else:
            raise AssertionError('Loaded instruction adoption was not held')
        saved(root / 'release-original.json', await rpc.call('thread/unsubscribe', {'threadId': thread}))
    finally:
        await rpc.close()
    rpc = client('cold', thread)
    try:
        await rpc.start()
        # Local lifecycle metadata readiness, not a model/progress loop. No
        # instruction request is sent while this exact QA context stays loaded.
        for _ in range(50):
            try:
                await require_cold_boundary(rpc, thread)
                break
            except ValueError:
                await asyncio.sleep(.1)
        else:
            raise AssertionError('Own QA context did not release; no resume attempted')
        overrides, revision = resume_overrides({'conversationParticipationPolicy': VERSION,
            'conversationResumeInstructions': {'baseInstructions': initial}})
        adoption_config = {**original, 'state': str(root / 'adoption-state'), 'nativeThreadId': thread,
            'conversationResumeInstructions': overrides, 'conversationParticipationPolicy': VERSION,
            'conversationInstructionAdoptionId': instructions_digest({'qaThread': thread, 'policy': VERSION})}
        adoption = InstructionAdoption(adoption_config, rpc, overrides)
        active = await adoption.begin()
        params = {'threadId': thread, 'excludeTurns': True, **active,
                  'toolPolicy': created['toolPolicy'], 'config': {'thread_unload_delay_secs': 30}}
        # The SAME known QA ceiling additionally makes native reject a loaded
        # race atomically; it neither grants nor changes tools.
        saved(root / 'cold-resume-intent.json', {'params': params, 'policyRevision': revision})
        resumed = await rpc.call('thread/resume', params)
        assert resumed['thread']['id'] == thread
        assert resumed['model'] == created['model']
        assert resumed['approvalPolicy'] == created['approvalPolicy'] and resumed['sandbox'] == created['sandbox']
        assert resumed['toolPolicy'] == created['toolPolicy'] == {'allowedTools': []}
        native_receipt = {'threadId': thread, 'resumed': True,
            'instructionOverridesSha256': instructions_digest(overrides),
            'participationPolicy': VERSION, **adoption.receipt_fields()}
        saved(Path(adoption_config['state']) / 'conversation-resume.json', native_receipt)
        # Preserve the ACK-before-acceptance crash window. Finish THAT original
        # operation from its saved ACK; no second native instruction request.
        recovered = InstructionAdoption(adoption_config, rpc, overrides)
        assert await recovered.begin() == {} and recovered.mode == 'accepted-loaded'
        acceptance_before = recovered.accepted.read_bytes()
        saved(root / 'cold-resume-accepted.json', {'threadId': thread, 'model': resumed['model'],
              'approvalPolicy': resumed['approvalPolicy'], 'sandbox': resumed['sandbox'],
              'toolPolicy': resumed['toolPolicy'], 'instructionRequestSha256': hashlib.sha256(
                  json.dumps(overrides, sort_keys=True).encode()).hexdigest()})
        saved(root / 'release-adopted.json', {'normalClientCloseOnly': True,
              'nativeInstructionAckFinishedWithoutResend': True, 'threadId': thread})
    finally:
        await rpc.close()
    rpc = client('loaded-reconnect', thread)
    try:
        await rpc.start()
        reconnected = InstructionAdoption(adoption_config, rpc, overrides)
        assert await reconnected.begin() == {} and reconnected.mode == 'accepted-loaded'
        # No instruction/model/permission/tool-policy replacement on loaded attach.
        attached = await rpc.call('thread/resume', {'threadId': thread, 'excludeTurns': True})
        assert attached['thread']['id'] == thread and attached['model'] == created['model']
        assert attached['approvalPolicy'] == created['approvalPolicy'] and attached['sandbox'] == created['sandbox']
        assert reconnected.accepted.read_bytes() == acceptance_before
        saved(Path(adoption_config['state']) / 'conversation-resume.json', {
            'threadId': thread, 'resumed': True, 'instructionOverridesSha256': instructions_digest(overrides),
            'participationPolicy': VERSION, **reconnected.receipt_fields()})
        again = InstructionAdoption(adoption_config, rpc, overrides)
        assert await again.begin() == {} and again.accepted.read_bytes() == acceptance_before
        saved(root / 'loaded-reconnect.json', {'sameThreadId': thread, 'policyFlagStillPresent': True,
            'noInstructionOverrideResent': True, 'originalAcceptanceUnchanged': True,
            'originalAckFinishNotRepeated': True})
    finally:
        await rpc.close()
    rpc = client('archive', thread)
    try:
        await rpc.start()
        await rpc.call('thread/archive', {'threadId': thread})
        saved(root / 'archive.json', {'threadId': thread, 'archivedOwnedQaOnly': True})
    finally:
        await rpc.close()
    after = Path('/proc/392451/exe').stat()
    assert (image.st_dev, image.st_ino, image.st_ctime_ns) == (after.st_dev, after.st_ino, after.st_ctime_ns)
    assert turns == []
    result = {'passed': True, 'nativePid': 392451, 'sameQaThread': thread,
        'loadedAdoptionHeld': loaded_held, 'actualColdResumeWithReviewedPolicy': VERSION,
        'originalAckFinishedWithoutResend': True, 'acceptedLoadedReconnectWithoutManualFlagRemoval': True,
        'sameOriginalQaModelPermissionsAndToolCeiling': True, 'nativeModelCalls': 0,
        'sharedNativeImageUnchanged': True, 'qaArchived': True,
        'productionContextsChanged': False,
        'limit': 'Native cold request/identity/settings proof, not a semantic model trial of the final-v2 wording or a production owner-drain approval'}
    saved(root / 'result.json', result)
    print(json.dumps(result))


asyncio.run(main())
