# Hollywood Stable Systems Research Notes (2026-04-24)

This note captures the research thread behind the next stability frontier for Losangelex/Hollywood.

The question is no longer whether teams can finish bounded tasks at all. They can.
The question is which coordination architecture is most likely to stay reliable, low-chatter, and quiescent over larger and longer-running work.

## Primary Sources

### 1. Contract Net / distributed problem solving

- R. G. Smith and R. Davis, _Frameworks for Cooperation in Distributed Problem Solving_ (1981):  
  <https://www.reidgsmith.com/Frameworks_for_Cooperation_in_Distributed_Problem_Solving_Jan-1981.pdf>

Key takeaways:

- Task-sharing and result-sharing solve different phases of cooperative work.
- Managers or integrating nodes are useful under uncertainty because they are best placed to synthesize partial work and direct subproblems.
- Excess peer-to-peer result sharing can distract workers and increase communication without improving outcomes.

This matches the Losangelex evidence that pure room chatter is not the right default and that some explicit coordination authority helps.

### 2. Organizational structure matters, and there is no single universal best

- Bryan Horling and Victor Lesser, _A Survey of Multi-Agent Organizational Paradigms_ (2005):  
  <https://mas.cs.umass.edu/Documents/bhorling/horling-paradigms.pdf>

Key takeaways:

- Organization materially changes system behavior and performance.
- Hierarchies, markets, teams, federations, matrix structures, and hybrids each trade off differently.
- Selection should depend on the environment rather than ideological preference for one fixed shape.

This directly supports the way we have been benchmarking multiple policies rather than assuming one “correct” social structure.

### 3. GPGP / coordination as modular constraints over local scheduling

- Keith Decker and Victor Lesser, _Designing a Family of Coordination Algorithms_ (1995):  
  <https://mas.cs.umass.edu/Documents/lesser/decker-94-14.pdf>
- Victor Lesser et al., _The Evolution of the GPGP/TÆMS Domain-Independent Coordination Framework_ (2004):  
  <https://mas.cs.umass.edu/Documents/lesser/GPGP_evol_AAMAS.pdf>

Key takeaways:

- Different coordination mechanisms are appropriate for different task environments.
- Coordination should work with an agent’s local scheduler rather than replacing it wholesale.
- Commitments, retractions, deadlines, and shared constraints are more important than verbose peer negotiation.
- Communication can happen at multiple abstraction levels instead of forcing every agent to share a full global plan.

This is the strongest classic argument for adding shared scheduling constraints and a blackboard/backlog style to Losangelex instead of relying on freeform room discourse.

### 4. Resource-centric dynamic task allocation

- Brian Gerkey and Maja Matarić, MURDOCH / auction-based multi-robot coordination overview:  
  <https://robotics.stanford.edu/~gerkey/research/murdoch.html>

Key takeaways:

- A Contract-Net-like auction works better when built on a resource-centric publish/subscribe model.
- Dynamic task allocation should operate on explicit resources and clear claims.
- Coordination in noisy, failure-prone environments benefits from simple explicit protocols instead of implicit assumptions.

This aligns with the Losangelex exact path-claim work: the system got more stable once ownership of concrete scope became part of task activation.

### 5. LLM-era organization and layered control

- Chen Qian et al., _ChatDev: Communicative Agents for Software Development_ (ACL 2024):  
  <https://aclanthology.org/2024.acl-long.810.pdf>
- _OrgAgent: Organize Your Multi-Agent System like a Company_ (arXiv 2026):  
  <https://arxiv.org/abs/2604.01020>

Key takeaways:

- Role structure and communication policy matter for LLM software-development teams.
- LLM agent systems still suffer from hallucination, drift, and fragmented process if communication is not constrained.
- A layered split between governance, execution, and compliance is a plausible improvement over flat teamwork.

These sources are consistent with our own benchmarks, where `leader_award` and related structured variants consistently outperform flat freeform coordination.

### 6. Quiescence is a distinct distributed-systems problem

- E. W. Dijkstra and C. S. Scholten, _Termination Detection for Diffusing Computations_ (EWD687):  
  <https://www.cs.utexas.edu/~EWD/transcriptions/EWD06xx/EWD687.html>
- Michel Raynal, _Distributed Termination Detection_ (2013 overview):  
  <https://www.researchgate.net/publication/299853636_Distributed_Termination_Detection>

Key takeaways:

- Global completion is not the same thing as locally observing all workers idle.
- In distributed systems, termination requires both passive workers and no in-flight work-producing messages.
- Termination/quiescence usually needs an explicit protocol rather than an implicit heuristic.

This maps almost perfectly to the current Losangelex problem where some policies can reach green but still leave threads active or loosely re-activatable after success.

## What This Suggests For Losangelex

The current evidence does **not** support one universal static policy.
It supports a layered architecture with explicit coordination substrate.

Most likely stable shape:

1. Governance layer
   - maintains work graph / ready queue / ownership
   - exposes exact ready lanes
   - reallocates when blockers or new facts appear

2. Execution layer
   - takes one exact lane at a time
   - posts concise commitments and handoffs
   - avoids broad-room negotiation

3. Compliance layer
   - keeps deterministic test signal fresh
   - challenges premature completion
   - owns quiescence and closure

4. Shared blackboard / backlog
   - exact scope
   - ownership state
   - blocker and dependency state
   - retractable commitments

5. Kernel underneath
   - durable tasks
   - exact path claims
   - wake gating
   - idempotent transitions

## Current Hypothesis

The most promising next step is not a more elaborate freeform “team culture.”
It is a hybrid of:

- hierarchy where uncertainty is high
- pull-based execution where lanes are clear
- blackboard/shared-constraint coordination to reduce chatter
- explicit compliance/quiescence control

The last item matters enough to stand alone:

- a stable long-running system will likely need an explicit quiescence or termination-detection protocol,
  not just better prompts that say “stop when done.”

That is what the next benchmark round tests.

## Current Benchmark Round

Campaign in progress:

- `leader_award`
- `kanban_pull`
- `dual_command`
- `org_layered`
- `gpgp_blackboard`

The first three are the empirical frontier so far.
The last two are the research-backed additions:

- `org_layered` is the governance / execution / compliance interpretation.
- `gpgp_blackboard` is the shared-constraint / local-scheduler interpretation.

## Empirical Follow-Through

The first decisive long-soak slice did not show a prompt-level winner for quiescence:

- `kanban_pull` was best on throughput
- `dual_command` was only slightly better on settling
- `org_layered` did not improve shutdown
- `gpgp_blackboard` was not competitive on the first challenge

An explicit prompt-level shutdown policy, `quiescence_token`, also failed to solve the problem:

- it reached green
- it executed the requested `IDLE-ACK` / `STILL-OWN` protocol in room traffic
- it still left all threads active after the soak window

So the research conclusion and the empirical conclusion now line up:

- organizational shape matters
- but long-horizon stability also needs a real termination-detection mechanism in the runtime
- prompt-only quiescence language is not sufficient
