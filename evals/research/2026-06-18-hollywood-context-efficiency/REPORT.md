# Hollywood Context Efficiency Evaluation

Generated: 2026-06-18T03:28:39Z

This is a narrow smoke evaluation of the model-visible Hollywood context change. It is not a full app-server team benchmark.

Model-in-the-loop runs: `codex exec --ephemeral`, model `gpt-5.5`, reasoning effort `low`, one repeat per scenario.

Fragment token counts are a simple `ceil(chars / 4)` approximation. `codex exec` input token counts include the fixed Codex harness context and cache effects, so they are useful for same-run comparisons but not fragment-only accounting.

## Fragment Size

Rows with Hollywood messages show message-fragment size. Rows without a message show whole prompt/context size. The long row is a deterministic message-only stress fixture.

| Scenario | Legacy approx tokens | Candidate approx tokens | Delta |
| --- | ---: | ---: | ---: |
| attention_no_action | 175 | 176 | 1 |
| direct_handoff_task_room | 218 | 226 | 8 |
| splittable_team_task_room | 363 | 763 | 400 |
| tiny_local_edit | 330 | 731 | 401 |
| long_unbounded_message_fragment | 114871 | 1620 | -113251 |

## Model-In-The-Loop Decisions

| Scenario | Variant | Passed | Action | Speak | Collaboration | Room | Input tokens | Total tokens |
| --- | --- | ---: | --- | ---: | ---: | --- | ---: | ---: |
| attention_no_action | legacy | True | stay_silent | False | False | repo/losangelex | 22196 | 22272 |
| attention_no_action | candidate | True | stay_silent | False | False | repo/losangelex | 22621 | 22692 |
| direct_handoff_task_room | legacy | False | claim_scope | False | False | repo/losangelex | 22242 | 22401 |
| direct_handoff_task_room | candidate | True | hollywood_send | True | False | repo/losangelex | 22676 | 23059 |
| splittable_team_task_room | legacy | False | hollywood_team_up | True | True | repo/losangelex | 22056 | 22192 |
| splittable_team_task_room | candidate | True | hollywood_team_up | True | True | task/losangelex/reconnect-jitter | 22472 | 22640 |
| tiny_local_edit | legacy | True | work_solo | False | False | repo/losangelex | 22036 | 22357 |
| tiny_local_edit | candidate | True | work_solo | False | False | repo/losangelex | 22452 | 22597 |
