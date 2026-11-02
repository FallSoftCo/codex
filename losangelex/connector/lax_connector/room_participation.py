"""Shared room participation instructions, not a message filter or wake policy."""
import json
import hashlib

VERSION = 'direct-human-v2'
PRIVATE_FINAL_LEGACY = ('Ordinary final text stays private; use hollywood_publish for deliberate '
                        'public updates/answers and explicit recipients for peer requests.')
FINAL_DELIVERY = ('Normal finals to humans or reply-eligible explicit requests are delivered automatically '
                  'to the original unambiguous source/audience. Use hollywood_publish for deliberate '
                  'routing, useful intermediate updates and peer requests; an accepted explicit '
                  'answer/blocked already supplies the final and suppresses an automatic copy.')
POLICY = """[LAX room participation: direct-human-v2]
Public human room input already reaches every agent member. Act from the original
human event on relevant existing local responsibility; do not wait for a Global
relay. Global is a peer with useful coordination duties, not a mandatory relay.
Do not repost the human's full brief, expand it into duplicate assignments for
members who already received it, or send acceptance/paraphrase-only chat.
Delegate when it adds a concrete assignment, resolves ownership, obtains a
dependency, or reaches a missing peer/host. Reference the original source and
add the delta, necessary inputs, preservation constraints and expected outcome.
A legitimate detailed handoff is welcome; this is not a message-length limit.
Publish useful evidence, intermediate results, essential questions and requested
summaries. Explicit direct requests remain actionable. While busy, judge new
input at the native boundary. Preserve the original human delivery, source and
audience; ordinary peer chatter must not create reply or progress-polling loops.
Normal finals to humans or reply-eligible explicit requests are delivered once
when the original source/audience is unambiguous. An accepted explicit
answer/blocked supplies that final; do not publish it and then repeat it as a
normal final. A useful intermediate update remains welcome, but finish with new
outcome information rather than a duplicate recap. Other peer chatter still
requires deliberate participation, not automatic answers.
[/LAX room participation]"""


def with_policy(instructions):
    if not isinstance(instructions, str):
        raise ValueError('Existing native instructions must be text')
    # Exact known room-mode bootstrap defect only, not a rewrite of arbitrary
    # owner restrictions or a claim that instructions can change delivery code.
    instructions = instructions.replace(PRIVATE_FINAL_LEGACY, FINAL_DELIVERY)
    if POLICY in instructions:
        return instructions
    return instructions.rstrip() + ('\n\n' if instructions.strip() else '') + POLICY


def input_guidance(audience):
    if audience == 'direct':
        return ('This is explicitly addressed private human input, not a room broadcast. '
                'Preserve its source/audience and assess relevance at the native boundary.')
    return ('This original human input already reached all room agent members. Act on relevant '
            'local responsibility without a Global relay or acknowledgement-only repost. '
            'Delegate only an additional concrete assignment/dependency/ownership delta or '
            'missing peer/host; preserve useful questions/results and busy-boundary relevance.')


def resume_overrides(config):
    overrides = config.get('conversationResumeInstructions', {})
    if (not isinstance(overrides, dict)
            or set(overrides) - {'baseInstructions', 'developerInstructions'}
            or any(not isinstance(value, str) or not value.strip() for value in overrides.values())):
        raise ValueError('Explicit native instruction overrides must use supported nonempty fields')
    overrides = dict(overrides)
    adoption = config.get('conversationParticipationPolicy')
    if adoption is not None:
        if adoption != VERSION:
            raise ValueError('Unknown reviewed room participation policy')
        if not overrides.get('baseInstructions'):
            raise ValueError('Participation adoption requires the reviewed original baseInstructions; '
                             'do not replace saved instructions with an inferred default')
        overrides['baseInstructions'] = with_policy(overrides['baseInstructions'])
    return overrides, adoption


def instructions_digest(overrides):
    return hashlib.sha256(json.dumps(overrides, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def release_patch(config, review, scope, expected_config_sha256):
    """Derive only the reviewed instruction delta inside existing release CAS."""
    if (config.get('runtimeMode') != 'room-conversation' or not config.get('nativeThreadId')
            or not isinstance(review, dict)
            or set(review) != {'policy', 'expectedResumeInstructionsSha256'}
            or review['policy'] != VERSION):
        raise ValueError('Exact room participation release review required')
    before = config.get('conversationResumeInstructions', {})
    if instructions_digest(before) != review['expectedResumeInstructionsSha256']:
        raise ValueError('Reviewed original instruction CAS changed')
    overrides, _ = resume_overrides({**config, 'conversationParticipationPolicy': VERSION})
    identity = instructions_digest({'scope': scope, 'thread': config['nativeThreadId'],
        'originalConfigurationSha256': expected_config_sha256, 'review': review,
        'renderedInstructionsSha256': instructions_digest(overrides)})
    patch = {'conversationParticipationPolicy': VERSION,
             'conversationResumeInstructions': overrides,
             'conversationInstructionAdoptionId': identity}
    return patch, {'adoptionId': identity, 'policy': VERSION, 'nativeThreadId': config['nativeThreadId'],
        'originalInstructionsSha256': instructions_digest(before),
        'renderedInstructionsSha256': instructions_digest(overrides)}


async def require_cold_boundary(rpc, thread):
    """A new transport is not proof the original native thread is unloaded.

    The owning release must fence concurrent connectors throughout this check
    and resume. This metadata read itself grants no ownership or stop authority.
    """
    if await loaded(rpc, thread):
        raise ValueError('Participation instruction adoption needs the original idle released '
                         'native thread; a connector reconnect cannot update a loaded context')


async def loaded(rpc, thread):
    cursor = None
    for _ in range(10):
        page = await rpc.call('thread/loaded/list', {'limit': 100, **({'cursor': cursor} if cursor else {})})
        if thread in page['data']:
            return True
        following = page.get('nextCursor')
        if not following:
            return False
        if following == cursor:
            break
        cursor = following
    raise ValueError('Native loaded-thread inspection is incomplete; instruction adoption held')


if __name__ == '__main__':
    import argparse
    from pathlib import Path
    from .runtime_files import private_file
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resume-instructions', type=Path,
                        help='Owner-private JSON containing reviewed baseInstructions and optional developerInstructions ONLY')
    args = parser.parse_args()
    if args.resume_instructions is None:
        print(json.dumps({'version': VERSION, 'policy': POLICY}))
    else:
        path = args.resume_instructions
        if not path.is_absolute() or path.resolve(strict=True) != path:
            raise ValueError('Exact original private instructions file required')
        private_file(path)
        if path.stat().st_size > 131072:
            raise ValueError('Instruction preparation exceeded its metadata bound')
        raw = path.read_bytes()
        overrides, _ = resume_overrides({'conversationParticipationPolicy': VERSION,
                                         'conversationResumeInstructions': json.loads(raw)})
        print(json.dumps({'schema': 'lax-room-instruction-adoption-plan/v1',
            'originalInstructionsSha256': hashlib.sha256(raw).hexdigest(),
            'releaseRequestField': {'newConversationInstructionAdoption': {
                'policy': VERSION, 'expectedResumeInstructionsSha256': instructions_digest(json.loads(raw))}},
            'configPatch': {'conversationParticipationPolicy': VERSION,
                            'conversationResumeInstructions': overrides},
            'liveApplied': False}, sort_keys=True))
