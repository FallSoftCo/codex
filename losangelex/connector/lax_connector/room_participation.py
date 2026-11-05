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
    reply_scope = (' For public human broadcasts, everyone may read and prepare independently. '
                   'At answer readiness the publisher waits two seconds and checks actual peer replies. '
                   'If a peer has answered, compare for useful new information; do not repeat an answer '
                   'or post acknowledgement-only chat. Useful corrections, questions and additions remain welcome. '
                   'A rejected conditional publication was NOT sent; reconsider from its peer feedback. '
                   ' If inputs from several rooms or audiences share this native turn, '
                   'answer each relevant source explicitly with hollywood_publish and its '
                   'original sourceEventId, room and audience. An unscoped final cannot be '
                   'safely routed across those sources; native turn end is not work completion.')
    if audience == 'direct':
        return ('This is explicitly addressed private human input, not a room broadcast. '
                'Preserve its source/audience and assess relevance at the native boundary.' + reply_scope)
    return ('This original human input already reached all room agent members. Act on relevant '
            'local responsibility without a Global relay or acknowledgement-only repost. '
            'Delegate only an additional concrete assignment/dependency/ownership delta or '
            'missing peer/host; preserve useful questions/results and busy-boundary relevance.' + reply_scope)


def resume_overrides(config):
    overrides = config.get('conversationResumeInstructions', {})
    if (not isinstance(overrides, dict)
            or set(overrides) - {'baseInstructions', 'developerInstructions'}
            or any(not isinstance(value, str) or not value.strip() for value in overrides.values())):
        raise ValueError('Explicit native instruction overrides must use supported nonempty fields')
    overrides = dict(overrides)
    adoption = config.get('conversationParticipationPolicy')
    if adoption is not None:
        if adoption not in (VERSION,'lead-project-v1'):
            raise ValueError('Unknown reviewed room participation policy')
        if not overrides.get('baseInstructions'):
            raise ValueError('Participation adoption requires the reviewed original baseInstructions; '
                             'do not replace saved instructions with an inferred default')
        overrides['baseInstructions'] = (project_policy(overrides['baseInstructions'],config) if config.get('projectCommunication') else with_policy(overrides['baseInstructions']))
    if config.get('projectCommunication'):
        if not overrides.get('baseInstructions'):raise ValueError('Project role requires reviewed original base instructions')
        overrides['baseInstructions']=project_policy(overrides['baseInstructions'],config)
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

PROJECT_VERSION='lead-project-v1'


def project_policy(instructions, config):
    """Replace only our owned participation block, preserving other constraints."""
    import re
    from uuid import UUID
    binding=config['projectCommunication'];lead=str(UUID(binding['leadAgentId']))
    role='lead' if config['agentId']==lead else 'worker'
    text=re.sub(r'\[LAX room participation: [^\]]+\].*?\[/LAX room participation\]', '',instructions,flags=re.S).strip()
    # Only SDK-authored legacy directives are replaced. Owner instructions,
    # permissions, privacy constraints and unrelated developer text stay intact.
    for legacy in (PRIVATE_FINAL_LEGACY,FINAL_DELIVERY,
            'Publish important progress, questions and answers in their original room/audience; only explicitly private coordination is private.'):
        text=text.replace(legacy,'Use the selected project tools for deliberate communication; native execution remains activity. Human replies belong to the lead.')
    if role=='lead':
        policy=('You are this project\'s lead and the sole human point of contact. Own original human work; '
          'do not quote/paraphrase it as a relay. Keep human replies concise and decision-oriented; routine actions belong in activity, without acknowledgements or repeated preservation lists. Inspect lead_work for its original work IDs and dependencies. '
          'Execute useful local work directly. Use lead_assign for specific selected agents, one compact task '
          'with its expected result and necessary constraints; link longer evidence. Your delegated instructions '
          'are authoritative within the user\'s scope. Review material results and coordinate only needed peers. '
          'Resolve addressed peer questions with team_answer; use lead_attention for native technical callbacks. Decide technical matters yourself and ask the human only for a genuine preference or permission. Use lead_reply with the original workId for human progress, genuine user questions and completion. '
          'Do not claim queued work is running or done. Native finals are private; an ended turn is not completion. '
          'Before ending, record real waiting/paused/complete state, or leave useful ready work for bounded '
          'event-driven continuation. Do not poll agents, repeat unchanged dependencies or create blanket continue loops.')
    else:
        policy=('You are a local project worker. The project lead is '+lead+'. Its addressed assignments '
          'carry delegated authority within the user\'s scope; do not demand another human relay. '
          'Work on the assigned task on this host. Do not answer human room broadcasts or narrate to the room. '
          'Use team_report with the original taskId: concise result, meaningful progress or exact dependency '
          'and bounded evidence references. No acknowledgements, repeated preservation lists, copied briefs '
          'or raw transcripts. Routine execution stays in activity; send interim progress only when useful for deliberate inspection. Use a question or blocked result when a lead decision is needed. Full native output remains local. Do not claim success for accepted messages. '
          'After team_question, continue independent useful work or end the inference while waiting; its directed answer resumes you. Never wait/poll in shell commands or send routine waiting messages. Answer only addressed peer questions, using team_answer and the original questionEventId. Use team_question for a necessary scoped fact with one stable questionKey; do not poll peers or repeat unchanged questions. An answer is not a new request. Technical native questions go to the lead, genuine permission approvals '
          'retain their real human owner. Cross-host work is coordinated through the lead, not SSH.')
    return text+'\n\n[LAX room participation: '+PROJECT_VERSION+']\n'+policy+'\nPreserve explicit stops, unknown effects, original message IDs, private audiences, model/usage settings and actual permissions. Room membership is not a business-action grant.\n[/LAX room participation]'
