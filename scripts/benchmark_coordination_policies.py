#!/usr/bin/env python3
"""Benchmark coordination policies in a deterministic model-in-loop harness.

This harness keeps execution deterministic while leaving coordination decisions
to a real model via `codex exec --ephemeral`. It is not a full live app-server
team replay. It is a discrete-event benchmark for broad-goal decomposition and
allocation policy comparison.

The simulator provides:
- a broad user goal
- a team with capabilities
- hidden investigation probes that reveal executable tasks
- deterministic task durations, dependencies, and scope overlap

Each policy decides how idle agents should be assigned at each decision round.
The environment then executes those assignments deterministically and records:
- completion latency
- idle opportunities left unused
- duplicate target picks
- ownership/scope conflicts
- invalid actions
- model token overhead

Policies included here:
- room_message
- leader_award
- auto_match
- semantic_market
- speculative_swarm
- hybrid
"""

from __future__ import annotations

import argparse
import itertools
import json
import pathlib
import random
import re
import statistics
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass, field
from typing import Any


REPO_ROOT = pathlib.Path("/home/ai/Development/losangelex")
DEFAULT_CODEX = REPO_ROOT / "codex-rs/target/debug/codex"
DEFAULT_MODEL = "gpt-5.4"


@dataclass(frozen=True)
class AgentSpec:
    name: str
    capabilities: tuple[str, ...]


@dataclass(frozen=True)
class ProbeSpec:
    id: str
    title: str
    description: str
    capabilities: tuple[str, ...]
    duration: int
    reveals: tuple[str, ...]
    priority: int = 1
    scope_group: str | None = None


@dataclass(frozen=True)
class TaskSpec:
    id: str
    title: str
    description: str
    kind: str
    capabilities: tuple[str, ...]
    duration: int
    depends_on: tuple[str, ...] = ()
    priority: int = 1
    scope_group: str | None = None


@dataclass(frozen=True)
class ScenarioSpec:
    id: str
    broad_goal: str
    lead_agent: str
    agents: tuple[AgentSpec, ...]
    probes: tuple[ProbeSpec, ...]
    tasks: tuple[TaskSpec, ...]
    success_tasks: tuple[str, ...]


@dataclass
class WorkItem:
    agent: str
    target_id: str
    target_kind: str
    ready_at: int
    duration: int
    scope_group: str | None


@dataclass
class ActionChoice:
    agent: str
    action: str
    target_kind: str | None
    target_id: str | None
    confidence: float
    reason: str


@dataclass
class BidChoice:
    agent: str
    target_kind: str
    target_id: str
    confidence: float
    reason: str


@dataclass
class SimulationState:
    scenario: ScenarioSpec
    time: int = 0
    discovered_tasks: set[str] = field(default_factory=set)
    completed_tasks: set[str] = field(default_factory=set)
    completed_probes: set[str] = field(default_factory=set)
    in_progress: list[WorkItem] = field(default_factory=list)
    duplicate_attempts: int = 0
    scope_conflicts: int = 0
    invalid_actions: int = 0
    waits_with_work: int = 0
    idle_with_actionable_work: int = 0
    idle_agents_total: int = 0
    model_calls: int = 0
    model_tokens: int = 0
    deadlock: bool = False
    steps: int = 0
    execution_log: list[str] = field(default_factory=list)

    def busy_agents(self) -> set[str]:
        return {item.agent for item in self.in_progress}

    def idle_agents(self) -> list[AgentSpec]:
        busy = self.busy_agents()
        return [agent for agent in self.scenario.agents if agent.name not in busy]

    def completed_success(self) -> bool:
        return all(task_id in self.completed_tasks for task_id in self.scenario.success_tasks)

    def available_probes(self) -> list[ProbeSpec]:
        in_progress = {
            item.target_id for item in self.in_progress if item.target_kind == "probe"
        }
        return [
            probe
            for probe in self.scenario.probes
            if probe.id not in self.completed_probes and probe.id not in in_progress
        ]

    def available_tasks(self) -> list[TaskSpec]:
        in_progress = {
            item.target_id for item in self.in_progress if item.target_kind == "task"
        }
        tasks = []
        for task in self.scenario.tasks:
            if task.id not in self.discovered_tasks:
                continue
            if task.id in self.completed_tasks or task.id in in_progress:
                continue
            if any(dep not in self.completed_tasks for dep in task.depends_on):
                continue
            tasks.append(task)
        return tasks

    def eligible_targets_for_agent(self, agent: AgentSpec) -> list[tuple[str, str]]:
        eligible: list[tuple[str, str]] = []
        for probe in self.available_probes():
            if set(agent.capabilities) & set(probe.capabilities):
                eligible.append(("probe", probe.id))
        for task in self.available_tasks():
            if set(agent.capabilities) & set(task.capabilities):
                eligible.append(("task", task.id))
        return eligible

    def snapshot(self) -> dict[str, Any]:
        probes = [
            {
                "id": probe.id,
                "title": probe.title,
                "description": probe.description,
                "capabilities": list(probe.capabilities),
                "duration": probe.duration,
                "priority": probe.priority,
            }
            for probe in self.available_probes()
        ]
        tasks = [
            {
                "id": task.id,
                "title": task.title,
                "description": task.description,
                "kind": task.kind,
                "capabilities": list(task.capabilities),
                "duration": task.duration,
                "priority": task.priority,
                "depends_on": list(task.depends_on),
            }
            for task in self.available_tasks()
        ]
        busy = [
            {
                "agent": item.agent,
                "target_kind": item.target_kind,
                "target_id": item.target_id,
                "ready_at": item.ready_at,
            }
            for item in sorted(self.in_progress, key=lambda item: (item.ready_at, item.agent))
        ]
        return {
            "time": self.time,
            "broad_goal": self.scenario.broad_goal,
            "lead_agent": self.scenario.lead_agent,
            "idle_agents": [
                {"name": agent.name, "capabilities": list(agent.capabilities)}
                for agent in self.idle_agents()
            ],
            "busy_agents": busy,
            "available_probes": probes,
            "available_tasks": tasks,
            "completed_probes": sorted(self.completed_probes),
            "completed_tasks": sorted(self.completed_tasks),
            "recent_log": self.execution_log[-6:],
        }

    def advance_to_next_completion(self) -> None:
        if not self.in_progress:
            self.deadlock = True
            return
        next_ready = min(item.ready_at for item in self.in_progress)
        self.time = next_ready
        finished = [item for item in self.in_progress if item.ready_at == next_ready]
        self.in_progress = [item for item in self.in_progress if item.ready_at != next_ready]
        for item in finished:
            if item.target_kind == "probe":
                self.completed_probes.add(item.target_id)
                probe = probe_map(self.scenario)[item.target_id]
                self.discovered_tasks.update(probe.reveals)
                self.execution_log.append(
                    f"t={self.time}: {item.agent} completed probe {item.target_id}"
                )
            else:
                self.completed_tasks.add(item.target_id)
                self.execution_log.append(
                    f"t={self.time}: {item.agent} completed task {item.target_id}"
                )

    def advance_until_decision(self) -> None:
        while True:
            if self.completed_success():
                return
            idle = self.idle_agents()
            if idle and (self.available_probes() or self.available_tasks()):
                return
            self.advance_to_next_completion()
            if self.deadlock:
                return


SCENARIOS: dict[str, ScenarioSpec] = {
    "feature_patch_chain": ScenarioSpec(
        id="feature_patch_chain",
        broad_goal=(
            "Ship the pronunciation snapshot feature across backend protocol, UI surfaces, "
            "and browser verification. The exact sequence is not specified up front."
        ),
        lead_agent="tony",
        agents=(
            AgentSpec("tony", ("planning", "backend", "integration")),
            AgentSpec("james", ("frontend", "ui", "review")),
            AgentSpec("chris", ("backend", "review", "qa")),
            AgentSpec("ray", ("browser", "qa", "tests")),
        ),
        probes=(
            ProbeSpec(
                id="probe_protocol",
                title="Inspect backend protocol changes",
                description="Figure out what protocol/data-layer change must land first.",
                capabilities=("planning", "backend", "integration"),
                duration=1,
                reveals=("task_protocol_impl", "task_ui_impl"),
                priority=5,
                scope_group="backend-core",
            ),
            ProbeSpec(
                id="probe_browser",
                title="Inspect browser verification lane",
                description="Determine what browser validation will be needed once implementation lands.",
                capabilities=("browser", "qa", "tests"),
                duration=1,
                reveals=("task_browser_qa",),
                priority=3,
                scope_group="browser-lane",
            ),
        ),
        tasks=(
            TaskSpec(
                id="task_protocol_impl",
                title="Implement protocol snapshot changes",
                description="Update backend protocol and persistence for pronunciation snapshots.",
                kind="implementation",
                capabilities=("backend", "integration"),
                duration=3,
                priority=5,
                scope_group="backend-core",
            ),
            TaskSpec(
                id="task_ui_impl",
                title="Implement UI snapshot surfaces",
                description="Update UI surfaces to consume the new pronunciation snapshot data.",
                kind="implementation",
                capabilities=("frontend", "ui"),
                duration=2,
                depends_on=("task_protocol_impl",),
                priority=4,
                scope_group="ui-surface",
            ),
            TaskSpec(
                id="task_browser_qa",
                title="Verify browser snapshot behavior",
                description="Run browser-level validation and summarize any failures.",
                kind="qa",
                capabilities=("browser", "qa", "tests"),
                duration=1,
                depends_on=("task_protocol_impl", "task_ui_impl"),
                priority=4,
                scope_group="browser-lane",
            ),
        ),
        success_tasks=("task_protocol_impl", "task_ui_impl", "task_browser_qa"),
    ),
    "broad_qa_cleanup": ScenarioSpec(
        id="broad_qa_cleanup",
        broad_goal=(
            "Audit the Hollywood room state for stale coordination residue, verify the awarded "
            "summary wording, and check the browser lane so the room converges on one clean result."
        ),
        lead_agent="tony",
        agents=(
            AgentSpec("tony", ("planning", "coordination", "review")),
            AgentSpec("james", ("qa", "review", "coordination")),
            AgentSpec("chris", ("qa", "coordination", "analysis")),
            AgentSpec("ray", ("browser", "qa", "tests")),
        ),
        probes=(
            ProbeSpec(
                id="probe_room_cleanup",
                title="Inspect stale room/board residue",
                description="Find whether there is stale coordination residue that needs cleanup.",
                capabilities=("coordination", "review", "analysis"),
                duration=1,
                reveals=("task_cleanup_stale", "task_final_report"),
                priority=4,
                scope_group="room-state",
            ),
            ProbeSpec(
                id="probe_award_wording",
                title="Inspect award summary wording",
                description="Check the durable award summary wording visible in Hollywood.",
                capabilities=("qa", "review", "coordination"),
                duration=1,
                reveals=("task_award_summary", "task_final_report"),
                priority=4,
                scope_group="room-state",
            ),
            ProbeSpec(
                id="probe_browser_lane",
                title="Inspect browser lane ownership",
                description="Check the browser lane and summarize whether there is a clean owner.",
                capabilities=("browser", "qa", "tests"),
                duration=1,
                reveals=("task_browser_lane", "task_final_report"),
                priority=5,
                scope_group="browser-lane",
            ),
        ),
        tasks=(
            TaskSpec(
                id="task_cleanup_stale",
                title="Clean stale coordination residue",
                description="Summarize the stale residue and record the cleanup result.",
                kind="coordination",
                capabilities=("coordination", "analysis", "review"),
                duration=1,
                priority=4,
                scope_group="room-state",
            ),
            TaskSpec(
                id="task_award_summary",
                title="Verify award summary wording",
                description="Confirm the Hollywood wording for the awarded summary.",
                kind="qa",
                capabilities=("qa", "review", "coordination"),
                duration=1,
                priority=4,
                scope_group="room-state",
            ),
            TaskSpec(
                id="task_browser_lane",
                title="Verify browser lane owner",
                description="Confirm whether the browser lane has a clean owner and summarize the result.",
                kind="qa",
                capabilities=("browser", "qa", "tests"),
                duration=1,
                priority=5,
                scope_group="browser-lane",
            ),
            TaskSpec(
                id="task_final_report",
                title="Synthesize one clean room conclusion",
                description="Post one final conclusion after the room and browser checks finish.",
                kind="review",
                capabilities=("planning", "review", "coordination"),
                duration=1,
                depends_on=("task_cleanup_stale", "task_award_summary", "task_browser_lane"),
                priority=5,
                scope_group="room-summary",
            ),
        ),
        success_tasks=(
            "task_cleanup_stale",
            "task_award_summary",
            "task_browser_lane",
            "task_final_report",
        ),
    ),
    "ambiguous_split": ScenarioSpec(
        id="ambiguous_split",
        broad_goal=(
            "A vague collaboration regression may involve backend sync, UI state, browser "
            "verification, and release-note fallout. Investigate the real lanes, split the work, "
            "and ship one clean synthesis without leaving capable agents idle."
        ),
        lead_agent="tony",
        agents=(
            AgentSpec("tony", ("planning", "backend", "integration")),
            AgentSpec("james", ("frontend", "ui", "review")),
            AgentSpec("chris", ("backend", "analysis", "review")),
            AgentSpec("ray", ("browser", "qa", "tests")),
        ),
        probes=(
            ProbeSpec(
                id="probe_backend_sync",
                title="Inspect backend sync lane",
                description="Determine whether the regression begins in backend sync and what code path must change.",
                capabilities=("planning", "backend", "integration", "analysis"),
                duration=1,
                reveals=("task_backend_fix", "task_final_report"),
                priority=5,
                scope_group="backend-core",
            ),
            ProbeSpec(
                id="probe_ui_state",
                title="Inspect UI state lane",
                description="Determine what UI surface is impacted and what change would be needed once backend semantics settle.",
                capabilities=("frontend", "ui", "review"),
                duration=1,
                reveals=("task_ui_fix", "task_final_report"),
                priority=4,
                scope_group="ui-surface",
            ),
            ProbeSpec(
                id="probe_browser_verify",
                title="Inspect browser verification lane",
                description="Determine what browser-level verification or regression test will be needed after implementation.",
                capabilities=("browser", "qa", "tests"),
                duration=1,
                reveals=("task_browser_verify", "task_final_report"),
                priority=4,
                scope_group="browser-lane",
            ),
            ProbeSpec(
                id="probe_release_note",
                title="Inspect release-note / rollout lane",
                description="Determine whether a short rollout note or migration note is required once the real fix lands.",
                capabilities=("planning", "review", "analysis"),
                duration=1,
                reveals=("task_release_note", "task_final_report"),
                priority=3,
                scope_group="room-summary",
            ),
        ),
        tasks=(
            TaskSpec(
                id="task_backend_fix",
                title="Implement backend sync fix",
                description="Land the backend synchronization fix for the collaboration regression.",
                kind="implementation",
                capabilities=("backend", "integration", "analysis"),
                duration=3,
                priority=5,
                scope_group="backend-core",
            ),
            TaskSpec(
                id="task_ui_fix",
                title="Implement UI state fix",
                description="Update the UI state handling once the backend fix is understood.",
                kind="implementation",
                capabilities=("frontend", "ui"),
                duration=2,
                depends_on=("task_backend_fix",),
                priority=4,
                scope_group="ui-surface",
            ),
            TaskSpec(
                id="task_browser_verify",
                title="Verify browser behavior",
                description="Run browser verification for the collaboration regression and summarize the result.",
                kind="qa",
                capabilities=("browser", "qa", "tests"),
                duration=1,
                depends_on=("task_backend_fix", "task_ui_fix"),
                priority=4,
                scope_group="browser-lane",
            ),
            TaskSpec(
                id="task_release_note",
                title="Write rollout note",
                description="Draft the short release or migration note once the backend lane is known.",
                kind="review",
                capabilities=("planning", "review", "analysis"),
                duration=1,
                depends_on=("task_backend_fix",),
                priority=3,
                scope_group="room-summary",
            ),
            TaskSpec(
                id="task_final_report",
                title="Publish one clean synthesis",
                description="Write the final synthesis after implementation, browser verification, and rollout note are complete.",
                kind="review",
                capabilities=("planning", "review", "integration"),
                duration=1,
                depends_on=("task_browser_verify", "task_release_note"),
                priority=5,
                scope_group="room-summary",
            ),
        ),
        success_tasks=(
            "task_backend_fix",
            "task_ui_fix",
            "task_browser_verify",
            "task_release_note",
            "task_final_report",
        ),
    ),
}


POLICY_DESCRIPTIONS = {
    "room_message": (
        "Simulate the current human-room style. Agents coordinate through broad shared intent "
        "and free-form room understanding. They may hesitate if ownership is not obvious."
    ),
    "leader_award": (
        "One lead agent decomposes and assigns. Keep accountability clear, saturate the team, "
        "and avoid duplicate or overlapping work."
    ),
    "strict_leader_award": (
        "A single lead agent owns decomposition. Only the lead should initiate probes that create "
        "new lanes; non-leads wait for discovered work or explicit assignments."
    ),
    "auto_match": (
        "Deterministic backend matcher. Assign the best available capable idle agent to the most "
        "urgent actionable item with no model judgment."
    ),
    "semantic_market": (
        "Each idle agent bids probabilistically on work it thinks it can help with, including "
        "confidence and scope fit. Backend picks a non-overlapping set of bids."
    ),
    "independent_market": (
        "Each idle agent independently decides what to bid for from its own perspective. "
        "Agents should use semantic judgment about marginal value, likely peer choices, and "
        "information gain; backend only resolves conflicts after the fact."
    ),
    "speculative_swarm": (
        "Idle agents should aggressively avoid waiting by taking diverse low-cost semantic probes "
        "or narrow tasks when they can create information or progress."
    ),
    "predictive_swarm": (
        "Each idle agent independently predicts what peers are likely to take this round and then "
        "chooses the complementary action with the highest marginal team value."
    ),
    "hybrid": (
        "Use leader-style assignment for dependency-sensitive sequencing, but rely on model "
        "judgment and self-selection for open QA/review/help work."
    ),
}


ASSIGNMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "assignments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "agent": {"type": "string"},
                    "action": {"type": "string"},
                    "target_kind": {"type": ["string", "null"]},
                    "target_id": {"type": ["string", "null"]},
                    "confidence": {"type": "number"},
                    "reason": {"type": "string"},
                },
                "required": [
                    "agent",
                    "action",
                    "target_kind",
                    "target_id",
                    "confidence",
                    "reason",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["assignments"],
    "additionalProperties": False,
}

MARKET_SCHEMA = {
    "type": "object",
    "properties": {
        "bids": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "agent": {"type": "string"},
                    "target_kind": {"type": "string"},
                    "target_id": {"type": "string"},
                    "confidence": {"type": "number"},
                    "reason": {"type": "string"},
                },
                "required": ["agent", "target_kind", "target_id", "confidence", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["bids"],
    "additionalProperties": False,
}

SINGLE_ACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string"},
        "target_kind": {"type": ["string", "null"]},
        "target_id": {"type": ["string", "null"]},
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["action", "target_kind", "target_id", "confidence", "reason"],
    "additionalProperties": False,
}

SINGLE_AGENT_BIDS_SCHEMA = {
    "type": "object",
    "properties": {
        "bids": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "target_kind": {"type": "string"},
                    "target_id": {"type": "string"},
                    "confidence": {"type": "number"},
                    "reason": {"type": "string"},
                },
                "required": ["target_kind", "target_id", "confidence", "reason"],
                "additionalProperties": False,
            },
            "maxItems": 2,
        }
    },
    "required": ["bids"],
    "additionalProperties": False,
}


def probe_map(scenario: ScenarioSpec) -> dict[str, ProbeSpec]:
    return {probe.id: probe for probe in scenario.probes}


def task_map(scenario: ScenarioSpec) -> dict[str, TaskSpec]:
    return {task.id: task for task in scenario.tasks}


def shuffled(values: list[Any], rng: random.Random) -> list[Any]:
    items = list(values)
    rng.shuffle(items)
    return items


def find_agent(scenario: ScenarioSpec, name: str) -> AgentSpec | None:
    for agent in scenario.agents:
        if agent.name == name:
            return agent
    return None


def validate_scenario(scenario: ScenarioSpec) -> None:
    task_ids = {task.id for task in scenario.tasks}
    revealed: set[str] = set()
    for probe in scenario.probes:
        for task_id in probe.reveals:
            if task_id not in task_ids:
                raise ValueError(
                    f"scenario {scenario.id}: probe {probe.id} reveals unknown task {task_id}"
                )
            revealed.add(task_id)
    unrevealed = sorted(task_id for task_id in task_ids if task_id not in revealed)
    if unrevealed:
        raise ValueError(
            f"scenario {scenario.id}: tasks are never revealed by any probe: {', '.join(unrevealed)}"
        )
    for task in scenario.tasks:
        unknown_deps = sorted(dep for dep in task.depends_on if dep not in task_ids)
        if unknown_deps:
            raise ValueError(
                f"scenario {scenario.id}: task {task.id} depends on unknown task(s): "
                + ", ".join(unknown_deps)
            )
    missing_success = sorted(task_id for task_id in scenario.success_tasks if task_id not in task_ids)
    if missing_success:
        raise ValueError(
            f"scenario {scenario.id}: success task(s) missing from task set: "
            + ", ".join(missing_success)
        )


def parse_tokens(stderr: str) -> int:
    match = re.search(r"tokens used\s*([\d,]+)", stderr, re.IGNORECASE)
    if not match:
        return 0
    return int(match.group(1).replace(",", ""))


def run_model(
    *,
    codex: pathlib.Path,
    model: str,
    prompt: str,
    schema: dict[str, Any],
) -> tuple[dict[str, Any], int]:
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as schema_file:
        json.dump(schema, schema_file)
        schema_path = pathlib.Path(schema_file.name)
    with tempfile.NamedTemporaryFile(delete=False) as output_file:
        output_path = pathlib.Path(output_file.name)

    command = [
        str(codex),
        "exec",
        "--ephemeral",
        "--color",
        "never",
        "-C",
        str(REPO_ROOT),
        "-m",
        model,
        "--output-schema",
        str(schema_path),
        "-o",
        str(output_path),
        prompt,
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"codex exec failed with rc={result.returncode}\nSTDERR:\n{result.stderr}"
        )
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    return payload, parse_tokens(result.stderr)


def heuristic_auto_match(state: SimulationState) -> list[ActionChoice]:
    raise RuntimeError("heuristic_auto_match now requires an RNG")


def heuristic_auto_match_with_rng(
    state: SimulationState, rng: random.Random
) -> list[ActionChoice]:
    available_tasks = shuffled(
        sorted(state.available_tasks(), key=lambda task: (-task.priority, task.duration, task.id)),
        rng,
    )
    available_probes = shuffled(
        sorted(
            state.available_probes(),
            key=lambda probe: (-probe.priority, probe.duration, probe.id),
        ),
        rng,
    )
    remaining_agents = shuffled(state.idle_agents(), rng)
    assignments: list[ActionChoice] = []
    taken_targets: set[tuple[str, str]] = set()
    for agent in remaining_agents:
        best: tuple[int, float, str, str] | None = None
        for task in available_tasks:
            if ("task", task.id) in taken_targets:
                continue
            if not (set(agent.capabilities) & set(task.capabilities)):
                continue
            score = task.priority * 10 + len(set(agent.capabilities) & set(task.capabilities))
            candidate = (score, rng.random(), "task", task.id)
            if best is None or candidate > best:
                best = candidate
        for probe in available_probes:
            if ("probe", probe.id) in taken_targets:
                continue
            if not (set(agent.capabilities) & set(probe.capabilities)):
                continue
            score = probe.priority * 10 + len(set(agent.capabilities) & set(probe.capabilities))
            candidate = (score, rng.random(), "probe", probe.id)
            if best is None or candidate > best:
                best = candidate
        if best is None:
            assignments.append(
                ActionChoice(
                    agent=agent.name,
                    action="wait",
                    target_kind=None,
                    target_id=None,
                    confidence=0.0,
                    reason="No eligible actionable work.",
                )
            )
            continue
        _, _, target_kind, target_id = best
        taken_targets.add((target_kind, target_id))
        assignments.append(
            ActionChoice(
                agent=agent.name,
                action="take",
                target_kind=target_kind,
                target_id=target_id,
                confidence=1.0,
                reason="Deterministic best-fit assignment.",
            )
        )
    return assignments


def prompt_state_view(
    state: SimulationState,
    *,
    rng: random.Random,
    perspective_agent: AgentSpec | None = None,
    repeat: int,
) -> dict[str, Any]:
    snapshot = state.snapshot()
    snapshot["idle_agents"] = shuffled(snapshot["idle_agents"], rng)
    snapshot["busy_agents"] = shuffled(snapshot["busy_agents"], rng)
    snapshot["available_probes"] = shuffled(snapshot["available_probes"], rng)
    snapshot["available_tasks"] = shuffled(snapshot["available_tasks"], rng)
    snapshot["completed_probes"] = shuffled(snapshot["completed_probes"], rng)
    snapshot["completed_tasks"] = shuffled(snapshot["completed_tasks"], rng)
    snapshot["trial_repeat"] = repeat
    if perspective_agent is not None:
        snapshot["perspective_agent"] = {
            "name": perspective_agent.name,
            "capabilities": list(perspective_agent.capabilities),
        }
        snapshot["other_idle_agents"] = [
            agent for agent in snapshot["idle_agents"] if agent["name"] != perspective_agent.name
        ]
    return snapshot


def assignment_prompt(
    policy: str,
    state: SimulationState,
    *,
    rng: random.Random,
    repeat: int,
) -> str:
    idle_agents = [agent.name for agent in shuffled(state.idle_agents(), rng)]
    return textwrap.dedent(
        f"""
        You are evaluating Losangelex coordination policy behavior in a deterministic harness.

        Policy under test: `{policy}`
        Policy semantics:
        {POLICY_DESCRIPTIONS[policy]}

        Important rules:
        - Keep eligible agents busy when real actionable work exists.
        - Avoid duplicate target picks and overlapping scope.
        - Respect dependencies by only choosing currently available tasks or probes.
        - Return at most one action per idle agent listed below.
        - Use `wait` only when there is no worthwhile eligible action for that agent right now.
        - If choosing a task or probe, set `action` to `take`.
        - `target_kind` must be `task`, `probe`, or null for `wait`.

        Idle agents this round:
        {json.dumps(idle_agents)}

        Current world state:
        {json.dumps(prompt_state_view(state, rng=rng, repeat=repeat), indent=2)}

        Return JSON only.
        """
    ).strip()


def market_prompt(
    policy: str,
    state: SimulationState,
    *,
    rng: random.Random,
    repeat: int,
) -> str:
    idle_agents = [agent.name for agent in shuffled(state.idle_agents(), rng)]
    return textwrap.dedent(
        f"""
        You are evaluating Losangelex coordination policy behavior in a deterministic harness.

        Policy under test: `{policy}`
        Policy semantics:
        {POLICY_DESCRIPTIONS[policy]}

        Important rules:
        - Simulate per-agent probabilistic bidding, not a central perfect allocator.
        - Each idle agent may emit up to two bids on tasks or probes it believes are a strong fit.
        - Confidence should be between 0.0 and 1.0 and reflect genuine fit or expected information gain.
        - Prefer diverse, non-overlapping bids when possible.
        - If an agent truly has no good bid, omit it instead of inventing one.

        Idle agents this round:
        {json.dumps(idle_agents)}

        Current world state:
        {json.dumps(prompt_state_view(state, rng=rng, repeat=repeat), indent=2)}

        Return JSON only.
        """
    ).strip()


def single_agent_assignment_prompt(
    policy: str,
    state: SimulationState,
    agent: AgentSpec,
    *,
    rng: random.Random,
    repeat: int,
) -> str:
    extra_rule = ""
    if policy == "strict_leader_award":
        extra_rule = (
            "\n- Because you are evaluating the strict leader policy, if no actionable tasks exist "
            "yet and discovery probes are available, the lead should usually take exactly one "
            "high-value probe rather than waiting."
        )
    return textwrap.dedent(
        f"""
        You are simulating one Losangelex worker inside a deterministic coordination benchmark.

        Policy under test: `{policy}`
        Policy semantics:
        {POLICY_DESCRIPTIONS[policy]}

        You are agent `{agent.name}` with capabilities {json.dumps(list(agent.capabilities))}.

        Important rules:
        - Decide only for yourself.
        - Only choose targets that match your own capabilities.
        - Choose `take` only when you think the marginal team value is strong enough.
        - Predict which targets peers are most likely to take this round and avoid obvious overlap.
        - Prefer complementary work that creates information or forward progress.
        - If no worthwhile unique action is likely, return `wait`.
        - `target_kind` must be `task`, `probe`, or null for `wait`.
        {extra_rule}

        Current world state:
        {json.dumps(prompt_state_view(state, rng=rng, perspective_agent=agent, repeat=repeat), indent=2)}

        Return JSON only.
        """
    ).strip()


def single_agent_market_prompt(
    policy: str,
    state: SimulationState,
    agent: AgentSpec,
    *,
    rng: random.Random,
    repeat: int,
) -> str:
    return textwrap.dedent(
        f"""
        You are simulating one Losangelex worker inside a deterministic coordination benchmark.

        Policy under test: `{policy}`
        Policy semantics:
        {POLICY_DESCRIPTIONS[policy]}

        You are agent `{agent.name}` with capabilities {json.dumps(list(agent.capabilities))}.

        Important rules:
        - Emit up to two bids for work you personally think is a strong fit.
        - Bid based on marginal value, expected information gain, and likely peer choices.
        - Lower your confidence or omit a bid if a peer is a much better fit or likely to collide.
        - Do not invent unavailable work.

        Current world state:
        {json.dumps(prompt_state_view(state, rng=rng, perspective_agent=agent, repeat=repeat), indent=2)}

        Return JSON only.
        """
    ).strip()


def parse_assignment_response(
    payload: dict[str, Any], scenario: ScenarioSpec
) -> list[ActionChoice]:
    assignments = payload.get("assignments", [])
    parsed: list[ActionChoice] = []
    seen_agents: set[str] = set()
    for raw in assignments:
        agent = raw["agent"]
        if agent in seen_agents or find_agent(scenario, agent) is None:
            continue
        seen_agents.add(agent)
        parsed.append(
            ActionChoice(
                agent=agent,
                action=raw["action"],
                target_kind=raw["target_kind"],
                target_id=raw["target_id"],
                confidence=max(0.0, min(1.0, float(raw["confidence"]))),
                reason=raw["reason"],
            )
        )
    return parsed


def parse_market_response(payload: dict[str, Any], scenario: ScenarioSpec) -> list[BidChoice]:
    bids = payload.get("bids", [])
    parsed: list[BidChoice] = []
    for raw in bids:
        if find_agent(scenario, raw["agent"]) is None:
            continue
        parsed.append(
            BidChoice(
                agent=raw["agent"],
                target_kind=raw["target_kind"],
                target_id=raw["target_id"],
                confidence=max(0.0, min(1.0, float(raw["confidence"]))),
                reason=raw["reason"],
            )
        )
    return parsed


def parse_single_action_response(payload: dict[str, Any], agent: str) -> ActionChoice:
    return ActionChoice(
        agent=agent,
        action=payload["action"],
        target_kind=payload["target_kind"],
        target_id=payload["target_id"],
        confidence=max(0.0, min(1.0, float(payload["confidence"]))),
        reason=payload["reason"],
    )


def parse_single_agent_market_response(payload: dict[str, Any], agent: str) -> list[BidChoice]:
    bids = payload.get("bids", [])
    parsed: list[BidChoice] = []
    for raw in bids:
        parsed.append(
            BidChoice(
                agent=agent,
                target_kind=raw["target_kind"],
                target_id=raw["target_id"],
                confidence=max(0.0, min(1.0, float(raw["confidence"]))),
                reason=raw["reason"],
            )
        )
    return parsed


def scope_group_for_target(scenario: ScenarioSpec, target_kind: str, target_id: str) -> str | None:
    if target_kind == "probe":
        return probe_map(scenario)[target_id].scope_group
    return task_map(scenario)[target_id].scope_group


def duration_for_target(scenario: ScenarioSpec, target_kind: str, target_id: str) -> int:
    if target_kind == "probe":
        return probe_map(scenario)[target_id].duration
    return task_map(scenario)[target_id].duration


def eligible_for_target(agent: AgentSpec, scenario: ScenarioSpec, target_kind: str, target_id: str) -> bool:
    if target_kind == "probe":
        target = probe_map(scenario)[target_id]
        return bool(set(agent.capabilities) & set(target.capabilities))
    target = task_map(scenario)[target_id]
    return bool(set(agent.capabilities) & set(target.capabilities))


def target_exists(state: SimulationState, target_kind: str, target_id: str) -> bool:
    if target_kind == "probe":
        return any(probe.id == target_id for probe in state.available_probes())
    return any(task.id == target_id for task in state.available_tasks())


def pick_market_assignments(state: SimulationState, bids: list[BidChoice]) -> list[ActionChoice]:
    by_agent: dict[str, list[BidChoice]] = {}
    for bid in bids:
        by_agent.setdefault(bid.agent, []).append(bid)
    for bid_list in by_agent.values():
        bid_list.sort(key=lambda bid: bid.confidence, reverse=True)
    candidates = list(
        itertools.chain.from_iterable(
            bid_list[:2] for bid_list in by_agent.values()
        )
    )
    candidates.sort(key=lambda bid: (bid.confidence, bid.target_kind == "task"), reverse=True)

    chosen: list[ActionChoice] = []
    used_agents: set[str] = set()
    used_targets: set[tuple[str, str]] = set()
    used_scopes: set[str] = set()

    for bid in candidates:
        if bid.agent in used_agents:
            continue
        target_key = (bid.target_kind, bid.target_id)
        if target_key in used_targets:
            continue
        if not target_exists(state, bid.target_kind, bid.target_id):
            continue
        scope_group = scope_group_for_target(state.scenario, bid.target_kind, bid.target_id)
        if scope_group and scope_group in used_scopes:
            continue
        chosen.append(
            ActionChoice(
                agent=bid.agent,
                action="take",
                target_kind=bid.target_kind,
                target_id=bid.target_id,
                confidence=bid.confidence,
                reason=bid.reason,
            )
        )
        used_agents.add(bid.agent)
        used_targets.add(target_key)
        if scope_group:
            used_scopes.add(scope_group)

    for agent in state.idle_agents():
        if agent.name in used_agents:
            continue
        chosen.append(
            ActionChoice(
                agent=agent.name,
                action="wait",
                target_kind=None,
                target_id=None,
                confidence=0.0,
                reason="No selected bid.",
            )
        )
    return chosen


def enforce_strict_leader_award(
    state: SimulationState, assignments: list[ActionChoice]
) -> list[ActionChoice]:
    enforced: list[ActionChoice] = []
    lead = state.scenario.lead_agent
    for choice in assignments:
        if choice.action == "take" and choice.target_kind == "probe" and choice.agent != lead:
            enforced.append(
                ActionChoice(
                    agent=choice.agent,
                    action="wait",
                    target_kind=None,
                    target_id=None,
                    confidence=0.0,
                    reason="Strict leader policy: only the lead may initiate new discovery probes.",
                )
            )
            continue
        enforced.append(choice)
    return enforced


def strict_leader_discovery_blocked(state: SimulationState) -> bool:
    lead = state.scenario.lead_agent
    if lead not in state.busy_agents():
        return False
    available_tasks = state.available_tasks()
    for agent in state.idle_agents():
        if any(set(agent.capabilities) & set(task.capabilities) for task in available_tasks):
            return False
    return any(
        probe.id in {available.id for available in state.available_probes()}
        and set(agent.capabilities) & set(probe.capabilities)
        for probe in state.scenario.probes
        for agent in state.idle_agents()
    )


def decide_assignments(
    *,
    policy: str,
    state: SimulationState,
    codex: pathlib.Path,
    model: str,
    rng: random.Random,
    repeat: int,
) -> list[ActionChoice]:
    if policy == "auto_match":
        return heuristic_auto_match_with_rng(state, rng)
    if policy == "strict_leader_award" and not state.available_tasks():
        idle_agents = {agent.name: agent for agent in state.idle_agents()}
        assignments: list[ActionChoice] = []
        lead_agent = idle_agents.get(state.scenario.lead_agent)
        if lead_agent is not None and any(
            set(lead_agent.capabilities) & set(probe.capabilities)
            for probe in state.available_probes()
        ):
            prompt = single_agent_assignment_prompt(
                policy, state, lead_agent, rng=rng, repeat=repeat
            )
            payload, tokens = run_model(
                codex=codex,
                model=model,
                prompt=prompt,
                schema=SINGLE_ACTION_SCHEMA,
            )
            state.model_calls += 1
            state.model_tokens += tokens
            assignments.append(parse_single_action_response(payload, lead_agent.name))
        for agent_name in idle_agents:
            if agent_name == state.scenario.lead_agent:
                continue
            assignments.append(
                ActionChoice(
                    agent=agent_name,
                    action="wait",
                    target_kind=None,
                    target_id=None,
                    confidence=0.0,
                    reason="Strict leader policy: waiting for the lead to finish discovery.",
                )
            )
        return enforce_strict_leader_award(state, assignments)
    if policy == "semantic_market":
        prompt = market_prompt(policy, state, rng=rng, repeat=repeat)
        payload, tokens = run_model(codex=codex, model=model, prompt=prompt, schema=MARKET_SCHEMA)
        state.model_calls += 1
        state.model_tokens += tokens
        return pick_market_assignments(state, parse_market_response(payload, state.scenario))
    if policy == "independent_market":
        bids: list[BidChoice] = []
        for agent in shuffled(state.idle_agents(), rng):
            prompt = single_agent_market_prompt(
                policy, state, agent, rng=rng, repeat=repeat
            )
            payload, tokens = run_model(
                codex=codex,
                model=model,
                prompt=prompt,
                schema=SINGLE_AGENT_BIDS_SCHEMA,
            )
            state.model_calls += 1
            state.model_tokens += tokens
            bids.extend(parse_single_agent_market_response(payload, agent.name))
        return pick_market_assignments(state, bids)
    if policy == "predictive_swarm":
        assignments: list[ActionChoice] = []
        for agent in shuffled(state.idle_agents(), rng):
            prompt = single_agent_assignment_prompt(
                policy, state, agent, rng=rng, repeat=repeat
            )
            payload, tokens = run_model(
                codex=codex,
                model=model,
                prompt=prompt,
                schema=SINGLE_ACTION_SCHEMA,
            )
            state.model_calls += 1
            state.model_tokens += tokens
            assignments.append(parse_single_action_response(payload, agent.name))
        return assignments

    prompt = assignment_prompt(policy, state, rng=rng, repeat=repeat)
    payload, tokens = run_model(codex=codex, model=model, prompt=prompt, schema=ASSIGNMENT_SCHEMA)
    state.model_calls += 1
    state.model_tokens += tokens
    parsed = parse_assignment_response(payload, state.scenario)

    assigned_agents = {choice.agent for choice in parsed}
    for agent in state.idle_agents():
        if agent.name not in assigned_agents:
            parsed.append(
                ActionChoice(
                    agent=agent.name,
                    action="wait",
                    target_kind=None,
                    target_id=None,
                    confidence=0.0,
                    reason="No action emitted.",
                )
            )
    if policy == "strict_leader_award":
        parsed = enforce_strict_leader_award(state, parsed)
    return parsed


def apply_assignments(state: SimulationState, assignments: list[ActionChoice]) -> None:
    idle_map = {agent.name: agent for agent in state.idle_agents()}
    actionable_for_idle = {
        agent.name: bool(state.eligible_targets_for_agent(agent)) for agent in state.idle_agents()
    }
    for agent_name, has_work in actionable_for_idle.items():
        state.idle_agents_total += 1
        if has_work:
            state.idle_with_actionable_work += 0

    by_target: dict[tuple[str, str], list[ActionChoice]] = {}
    valid_waits: list[ActionChoice] = []
    for choice in assignments:
        agent = idle_map.get(choice.agent)
        if agent is None:
            continue
        if choice.action == "wait" or choice.target_kind is None or choice.target_id is None:
            valid_waits.append(choice)
            continue
        if choice.action != "take":
            state.invalid_actions += 1
            state.execution_log.append(
                f"t={state.time}: invalid action from {choice.agent}: {choice.action}"
            )
            continue
        if not target_exists(state, choice.target_kind, choice.target_id):
            state.invalid_actions += 1
            state.execution_log.append(
                f"t={state.time}: {choice.agent} chose unavailable {choice.target_kind} {choice.target_id}"
            )
            continue
        if not eligible_for_target(agent, state.scenario, choice.target_kind, choice.target_id):
            state.invalid_actions += 1
            state.execution_log.append(
                f"t={state.time}: {choice.agent} is ineligible for {choice.target_kind} {choice.target_id}"
            )
            continue
        by_target.setdefault((choice.target_kind, choice.target_id), []).append(choice)

    winners: list[ActionChoice] = []
    for target_key, choices in by_target.items():
        choices.sort(key=lambda choice: (choice.confidence, choice.agent), reverse=True)
        winners.append(choices[0])
        if len(choices) > 1:
            state.duplicate_attempts += len(choices) - 1
            state.execution_log.append(
                f"t={state.time}: duplicate picks for {target_key[0]} {target_key[1]} by "
                + ", ".join(choice.agent for choice in choices)
            )

    by_scope: dict[str, list[ActionChoice]] = {}
    final_winners: list[ActionChoice] = []
    for choice in winners:
        scope_group = scope_group_for_target(
            state.scenario, choice.target_kind or "", choice.target_id or ""
        )
        if not scope_group:
            final_winners.append(choice)
            continue
        by_scope.setdefault(scope_group, []).append(choice)

    taken_agents = {choice.agent for choice in final_winners}
    for scope_group, choices in by_scope.items():
        if len(choices) == 1:
            final_winners.append(choices[0])
            taken_agents.add(choices[0].agent)
            continue
        choices.sort(key=lambda choice: (choice.confidence, choice.agent), reverse=True)
        final_winners.append(choices[0])
        taken_agents.add(choices[0].agent)
        state.scope_conflicts += len(choices) - 1
        state.execution_log.append(
            f"t={state.time}: scope conflict on {scope_group} between "
            + ", ".join(choice.agent for choice in choices)
        )

    for choice in valid_waits:
        agent = idle_map[choice.agent]
        if state.eligible_targets_for_agent(agent):
            state.waits_with_work += 1
            state.idle_with_actionable_work += 1
            state.execution_log.append(
                f"t={state.time}: {choice.agent} waited despite eligible work"
            )

    for agent in state.idle_agents():
        if agent.name in taken_agents:
            continue
        if state.eligible_targets_for_agent(agent):
            chosen_wait = next(
                (choice for choice in valid_waits if choice.agent == agent.name), None
            )
            if chosen_wait is None:
                state.waits_with_work += 1
                state.idle_with_actionable_work += 1
                state.execution_log.append(
                    f"t={state.time}: {agent.name} left idle while work existed"
                )

    for choice in final_winners:
        duration = duration_for_target(
            state.scenario, choice.target_kind or "", choice.target_id or ""
        )
        scope_group = scope_group_for_target(
            state.scenario, choice.target_kind or "", choice.target_id or ""
        )
        state.in_progress.append(
            WorkItem(
                agent=choice.agent,
                target_id=choice.target_id or "",
                target_kind=choice.target_kind or "",
                ready_at=state.time + duration,
                duration=duration,
                scope_group=scope_group,
            )
        )
        state.execution_log.append(
            f"t={state.time}: {choice.agent} started {choice.target_kind} {choice.target_id}"
        )


def run_once(
    *,
    scenario: ScenarioSpec,
    policy: str,
    codex: pathlib.Path,
    model: str,
    max_rounds: int,
    repeat: int,
) -> dict[str, Any]:
    state = SimulationState(scenario=scenario)
    rng = random.Random(f"{scenario.id}:{policy}:{repeat}")
    rounds = 0

    while rounds < max_rounds:
        state.advance_until_decision()
        if state.completed_success() or state.deadlock:
            break
        if policy == "strict_leader_award" and strict_leader_discovery_blocked(state):
            state.advance_to_next_completion()
            if state.completed_success() or state.deadlock:
                break
            continue
        if not state.idle_agents():
            continue
        if not state.available_probes() and not state.available_tasks():
            state.deadlock = True
            break
        assignments = decide_assignments(
            policy=policy,
            state=state,
            codex=codex,
            model=model,
            rng=rng,
            repeat=repeat,
        )
        apply_assignments(state, assignments)
        if (
            policy == "strict_leader_award"
            and not state.available_tasks()
            and state.available_probes()
            and not state.in_progress
        ):
            state.deadlock = True
            break
        state.steps += 1
        rounds += 1

    while not state.completed_success() and state.in_progress:
        state.advance_until_decision()
        if state.deadlock:
            break

    success = state.completed_success()
    if not success and not state.deadlock:
        state.deadlock = True

    return {
        "scenario": scenario.id,
        "policy": policy,
        "success": success,
        "deadlock": state.deadlock,
        "completion_time": state.time if success else None,
        "rounds": state.steps,
        "duplicate_attempts": state.duplicate_attempts,
        "scope_conflicts": state.scope_conflicts,
        "invalid_actions": state.invalid_actions,
        "waits_with_work": state.waits_with_work,
        "idle_with_actionable_work": state.idle_with_actionable_work,
        "idle_agents_total": state.idle_agents_total,
        "idle_ratio": (
            state.idle_with_actionable_work / state.idle_agents_total
            if state.idle_agents_total
            else 0.0
        ),
        "model_calls": state.model_calls,
        "model_tokens": state.model_tokens,
        "log_tail": state.execution_log[-10:],
    }


def aggregate(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for result in results:
        grouped.setdefault((result["scenario"], result["policy"]), []).append(result)

    summary: list[dict[str, Any]] = []
    for (scenario, policy), runs in sorted(grouped.items()):
        successes = [run for run in runs if run["success"]]
        completion_times = [run["completion_time"] for run in successes if run["completion_time"]]
        summary.append(
            {
                "scenario": scenario,
                "policy": policy,
                "runs": len(runs),
                "success_rate": sum(1 for run in runs if run["success"]) / len(runs),
                "avg_completion_time": (
                    statistics.mean(completion_times) if completion_times else None
                ),
                "avg_idle_ratio": statistics.mean(run["idle_ratio"] for run in runs),
                "avg_duplicate_attempts": statistics.mean(
                    run["duplicate_attempts"] for run in runs
                ),
                "avg_scope_conflicts": statistics.mean(run["scope_conflicts"] for run in runs),
                "avg_invalid_actions": statistics.mean(run["invalid_actions"] for run in runs),
                "avg_model_calls": statistics.mean(run["model_calls"] for run in runs),
                "avg_model_tokens": statistics.mean(run["model_tokens"] for run in runs),
            }
        )
    return summary


def print_table(summary: list[dict[str, Any]]) -> None:
    headers = [
        "scenario",
        "policy",
        "success",
        "avg_time",
        "idle_ratio",
        "dup",
        "scope",
        "invalid",
        "calls",
        "tokens",
    ]
    rows = []
    for item in summary:
        rows.append(
            [
                item["scenario"],
                item["policy"],
                f"{item['success_rate']:.2f}",
                "-" if item["avg_completion_time"] is None else f"{item['avg_completion_time']:.2f}",
                f"{item['avg_idle_ratio']:.2f}",
                f"{item['avg_duplicate_attempts']:.2f}",
                f"{item['avg_scope_conflicts']:.2f}",
                f"{item['avg_invalid_actions']:.2f}",
                f"{item['avg_model_calls']:.2f}",
                f"{item['avg_model_tokens']:.0f}",
            ]
        )
    widths = [
        max(len(header), *(len(str(row[idx])) for row in rows))
        for idx, header in enumerate(headers)
    ]
    print(" ".join(header.ljust(widths[idx]) for idx, header in enumerate(headers)))
    print(" ".join("-" * width for width in widths))
    for row in rows:
        print(" ".join(str(cell).ljust(widths[idx]) for idx, cell in enumerate(row)))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--codex",
        default=str(DEFAULT_CODEX),
        help="Path to the codex binary.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="Model to use for codex exec decisions.",
    )
    parser.add_argument(
        "--scenario",
        choices=sorted(SCENARIOS),
        action="append",
        help="Scenario(s) to run. Defaults to all.",
    )
    parser.add_argument(
        "--policy",
        choices=sorted(POLICY_DESCRIPTIONS),
        action="append",
        help="Policy/policies to run. Defaults to all.",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=3,
        help="Number of repeats per scenario/policy pair.",
    )
    parser.add_argument(
        "--max-rounds",
        type=int,
        default=12,
        help="Maximum decision rounds per run.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print full JSON output instead of the summary table.",
    )
    args = parser.parse_args()

    codex = pathlib.Path(args.codex)
    scenarios = args.scenario or sorted(SCENARIOS)
    policies = args.policy or sorted(POLICY_DESCRIPTIONS)
    for scenario_id in scenarios:
        validate_scenario(SCENARIOS[scenario_id])

    results: list[dict[str, Any]] = []
    for scenario_id in scenarios:
        scenario = SCENARIOS[scenario_id]
        for policy in policies:
            for repeat in range(args.repeats):
                result = run_once(
                    scenario=scenario,
                    policy=policy,
                    codex=codex,
                    model=args.model,
                    max_rounds=args.max_rounds,
                    repeat=repeat + 1,
                )
                result["repeat"] = repeat + 1
                results.append(result)
                print(
                    f"completed scenario={scenario_id} policy={policy} repeat={repeat + 1}",
                    file=sys.stderr,
                    flush=True,
                )

    summary = aggregate(results)
    if args.json:
        print(
            json.dumps(
                {
                    "model": args.model,
                    "results": results,
                    "summary": summary,
                },
                indent=2,
            )
        )
    else:
        print_table(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
