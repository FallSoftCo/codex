#!/usr/bin/env python3
"""Run small model-in-the-loop checks against Hollywood synthetic brief fixtures.

This is not a full coordination replay harness. It is a narrow smoke test for the
model-facing brief layer added around Hollywood-triggered turns.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import tempfile
import textwrap


REPO_ROOT = pathlib.Path("/home/ai/Development/losangelex")
DEFAULT_CODEX = REPO_ROOT / "codex-rs/target/debug/codex"
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "speak": {"type": "boolean"},
        "action": {"type": "string"},
        "summary": {"type": "string"},
    },
    "required": ["speak", "action", "summary"],
    "additionalProperties": False,
}

SCENARIOS = {
    "scope_update_no_lane": textwrap.dedent(
        """
        You are deciding the next Hollywood coordination move for an attached Losangelex agent.

        Developer instruction:
        Hollywood attention update: inspect the attached Hollywood message from `ray` in room `repo/ozzz`. Keep it internal unless it materially changes your work or requires a concrete coordination action; do not send a routine acknowledgment by default.

        Developer instruction:
        Hollywood synthetic coordination brief:
        - wake reason: `semantic_delta`
        - semantic kind: `scope_update`
        - summary: `ray` updated ownership or scope in `repo/ozzz`.
        - fact: sender `ray` in room `repo/ozzz`
        - fact: message was an explicit broadcast
        - fact: this is a coordination delta; reply only if it materially changes your owned work
        - valid next moves:
          - check whether this changes your available lane or overlaps your owned paths
          - stay silent if there is still no clean lane
        - if this brief does not materially change your owned work or create a real obligation, stay silent instead of sending a routine acknowledgment.

        <hollywood_message>
        {"message_id":48,"room":"repo/ozzz","sender_id":"ray","mentions":[],"body":"Ray owns the browser lane; no clean lane for Duggs yet.","synthetic_brief":{"wake_reason":"semantic_delta","semantic_kind":"scope_update","summary":"`ray` updated ownership or scope in `repo/ozzz`.","facts":["sender `ray` in room `repo/ozzz`","message was an explicit broadcast","this is a coordination delta; reply only if it materially changes your owned work"],"suggested_actions":["check whether this changes your available lane or overlaps your owned paths","stay silent if there is still no clean lane"],"stay_silent_if_no_actionable_delta":true}}
        </hollywood_message>

        Assume there is still no clean lane for this agent. Return JSON only.
        """
    ).strip(),
    "direct_takeover_request": textwrap.dedent(
        """
        You are deciding the next Hollywood coordination move for an attached Losangelex agent.

        Developer instruction:
        Hollywood coordination obligation: a direct message in room `repo/ozzz` from `tony` needs explicit analysis and, if relevant, a concrete response, claim, join, handoff, or action. Do not silently ignore it.

        Developer instruction:
        Hollywood synthetic coordination brief:
        - wake reason: `direct_obligation`
        - semantic kind: `handoff`
        - summary: `tony` proposed a handoff in `repo/ozzz`.
        - fact: sender `tony` in room `repo/ozzz`
        - fact: you were directly mentioned
        - fact: the sender expects an explicit response or decision
        - valid next moves:
          - confirm only if you are taking the handoff
          - claim the exact replacement scope before editing

        <hollywood_message>
        {"message_id":77,"room":"repo/ozzz","sender_id":"tony","mentions":["duggs"],"body":"@duggs can you take over the browser-proof lane and own practice-surfaces.browser.test.ts?","synthetic_brief":{"wake_reason":"direct_obligation","semantic_kind":"handoff","summary":"`tony` proposed a handoff in `repo/ozzz`.","facts":["sender `tony` in room `repo/ozzz`","you were directly mentioned","the sender expects an explicit response or decision"],"suggested_actions":["confirm only if you are taking the handoff","claim the exact replacement scope before editing"],"stay_silent_if_no_actionable_delta":false}}
        </hollywood_message>

        Assume the agent is available and willing to take the handoff. Return JSON only.
        """
    ).strip(),
}


def run_scenario(codex: pathlib.Path, scenario: str) -> dict[str, object]:
    prompt = SCENARIOS[scenario]
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as schema_file:
        json.dump(OUTPUT_SCHEMA, schema_file)
        schema_path = pathlib.Path(schema_file.name)
    with tempfile.NamedTemporaryFile(delete=False) as out_file:
        output_path = pathlib.Path(out_file.name)

    command = [
        str(codex),
        "exec",
        "--ephemeral",
        "--color",
        "never",
        "-C",
        str(REPO_ROOT),
        "--output-schema",
        str(schema_path),
        "-o",
        str(output_path),
        prompt,
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise SystemExit(
            f"{scenario}: codex exec failed with rc={result.returncode}\n{result.stderr}"
        )
    return json.loads(output_path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--codex",
        default=str(DEFAULT_CODEX),
        help="Path to the codex binary to invoke.",
    )
    parser.add_argument(
        "--scenario",
        choices=sorted(SCENARIOS),
        action="append",
        help="Scenario(s) to run. Defaults to all.",
    )
    args = parser.parse_args()

    codex = pathlib.Path(args.codex)
    scenarios = args.scenario or list(SCENARIOS)
    results = {name: run_scenario(codex, name) for name in scenarios}
    json.dump(results, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
