use codex_tools::JsonSchema;
use codex_tools::ResponsesApiTool;
use codex_tools::ToolSpec;
use serde_json::Value;
use serde_json::json;
use std::collections::BTreeMap;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CommandToolOptions {
    pub allow_login_shell: bool,
    pub exec_permission_approvals_enabled: bool,
}

#[cfg(test)]
pub fn create_exec_command_tool(options: CommandToolOptions) -> ToolSpec {
    create_exec_command_tool_with_environment_id(options, /*include_environment_id*/ false)
}

pub(crate) fn create_exec_command_tool_with_environment_id(
    options: CommandToolOptions,
    include_environment_id: bool,
) -> ToolSpec {
    let mut properties = BTreeMap::from([
        (
            "cmd".to_string(),
            JsonSchema::string(Some("Shell command to execute.".to_string())),
        ),
        (
            "workdir".to_string(),
            JsonSchema::string(Some(
                "Working directory for the command. Defaults to the turn cwd."
                    .to_string(),
            )),
        ),
        (
            "shell".to_string(),
            JsonSchema::string(Some(
                "Shell binary to launch. Defaults to the user's default shell.".to_string(),
            )),
        ),
        (
            "tty".to_string(),
            JsonSchema::boolean(Some(
                "True allocates a PTY for the command; false or omitted uses plain pipes."
                    .to_string(),
            )),
        ),
        (
            "yield_time_ms".to_string(),
            JsonSchema::number(Some(
                "Wait before yielding output. Defaults to 10000 ms; effective range is 250-30000 ms.".to_string(),
            )),
        ),
        (
            "max_output_tokens".to_string(),
            JsonSchema::number(Some(
                "Output token budget. Defaults to 10000 tokens; larger requests may be capped by policy.".to_string(),
            )),
        ),
    ]);
    if options.allow_login_shell {
        properties.insert(
            "login".to_string(),
            JsonSchema::boolean(Some(
                "True runs the shell with -l/-i semantics; false disables them. Defaults to true."
                    .to_string(),
            )),
        );
    }
    if include_environment_id {
        properties.insert(
            "environment_id".to_string(),
            JsonSchema::string(Some(
                "Environment id from <environment_context>. Omit to use the primary environment."
                    .to_string(),
            )),
        );
    }
    properties.extend(create_approval_parameters(
        options.exec_permission_approvals_enabled,
    ));

    ToolSpec::Function(ResponsesApiTool {
        name: "exec_command".to_string(),
        description: if cfg!(windows) {
            format!(
                "Runs a command in a PTY, returning output or a session ID for ongoing interaction.\n\n{}",
                windows_shell_guidance()
            )
        } else {
            "Runs a command in a PTY, returning output or a session ID for ongoing interaction."
                .to_string()
        },
        strict: false,
        defer_loading: None,
        parameters: JsonSchema::object(
            properties,
            Some(vec!["cmd".to_string()]),
            Some(false.into()),
        ),
        output_schema: Some(unified_exec_output_schema()),
    })
}

pub fn create_watch_process_exit_tool() -> ToolSpec {
    let properties = BTreeMap::from([
        (
            "session_id".to_string(),
            JsonSchema::number(Some(
                "Identifier of the running exec_command session to watch for exit.".to_string(),
            )),
        ),
        (
            "title".to_string(),
            JsonSchema::string(Some("Short human-readable label for the watcher.".to_string())),
        ),
        (
            "prompt".to_string(),
            JsonSchema::string(Some(
                "Follow-up prompt injected into the thread after the process exits.".to_string(),
            )),
        ),
        (
            "timeout_seconds".to_string(),
            JsonSchema::number(Some(
                "Optional timeout in seconds. If the process is still unavailable when the timeout expires, the watcher fails."
                    .to_string(),
            )),
        ),
        (
            "thread_id".to_string(),
            JsonSchema::string(Some(
                "Optional thread/session id to wake. Defaults to the current thread."
                    .to_string(),
            )),
        ),
        (
            "requires_response".to_string(),
            JsonSchema::boolean(Some(
                "Whether the deferred wake should expect a concrete response.".to_string(),
            )),
        ),
    ]);

    ToolSpec::Function(ResponsesApiTool {
        name: "watch_process_exit".to_string(),
        description: "Registers a persisted watcher that wakes the thread when an existing exec_command session exits. Prefer this over long inline waiting when no reasoning is needed until the process finishes.".to_string(),
        strict: false,
        defer_loading: None,
        parameters: JsonSchema::object(
            properties,
            Some(vec![
                "session_id".to_string(),
                "title".to_string(),
                "prompt".to_string(),
            ]),
            Some(false.into()),
        ),
        output_schema: None,
    })
}

pub fn create_watch_agent_completion_tool() -> ToolSpec {
    let properties = BTreeMap::from([
        (
            "target".to_string(),
            JsonSchema::string(Some(
                "Identifier of the target agent/thread whose completion should wake the waiting thread."
                    .to_string(),
            )),
        ),
        (
            "title".to_string(),
            JsonSchema::string(Some("Short human-readable label for the watcher.".to_string())),
        ),
        (
            "prompt".to_string(),
            JsonSchema::string(Some(
                "Follow-up prompt injected into the thread after the target agent satisfies the condition."
                    .to_string(),
            )),
        ),
        (
            "condition".to_string(),
            JsonSchema::string(Some(
                "Optional completion condition: `final`, `completed`, or `successful`. Defaults to `final`."
                    .to_string(),
            )),
        ),
        (
            "timeout_seconds".to_string(),
            JsonSchema::number(Some(
                "Optional timeout in seconds. If the target agent does not satisfy the condition in time, the watcher fails."
                    .to_string(),
            )),
        ),
        (
            "thread_id".to_string(),
            JsonSchema::string(Some(
                "Optional thread/session id to wake. Defaults to the current thread."
                    .to_string(),
            )),
        ),
        (
            "requires_response".to_string(),
            JsonSchema::boolean(Some(
                "Whether the deferred wake should expect a concrete response.".to_string(),
            )),
        ),
    ]);

    ToolSpec::Function(ResponsesApiTool {
        name: "watch_agent_completion".to_string(),
        description: "Registers a persisted watcher that wakes the thread when another agent reaches a target completion state. Prefer this over stretching `wait_agent` into a long-lived blocking wait.".to_string(),
        strict: false,
        defer_loading: None,
        parameters: JsonSchema::object(
            properties,
            Some(vec![
                "target".to_string(),
                "title".to_string(),
                "prompt".to_string(),
            ]),
            Some(false.into()),
        ),
        output_schema: None,
    })
}

pub fn create_list_watchers_tool() -> ToolSpec {
    let properties = BTreeMap::from([(
        "thread_id".to_string(),
        JsonSchema::string(Some(
            "Optional thread/session id filter. Defaults to the current thread.".to_string(),
        )),
    )]);

    ToolSpec::Function(ResponsesApiTool {
        name: "list_watchers".to_string(),
        description:
            "List persisted deferred process-exit watchers for the current or specified thread."
                .to_string(),
        strict: false,
        defer_loading: None,
        parameters: JsonSchema::object(properties, Some(Vec::new()), Some(false.into())),
        output_schema: None,
    })
}

pub fn create_cancel_watcher_tool() -> ToolSpec {
    let properties = BTreeMap::from([(
        "watcher_id".to_string(),
        JsonSchema::string(Some("Watcher id to stop.".to_string())),
    )]);

    ToolSpec::Function(ResponsesApiTool {
        name: "cancel_watcher".to_string(),
        description: "Stop a persisted watcher so it will no longer wake the thread.".to_string(),
        strict: false,
        defer_loading: None,
        parameters: JsonSchema::object(
            properties,
            Some(vec!["watcher_id".to_string()]),
            Some(false.into()),
        ),
        output_schema: None,
    })
}

pub fn create_watch_task_periodically_tool() -> ToolSpec {
    let properties = BTreeMap::from([
        (
            "title".to_string(),
            JsonSchema::string(Some(
                "Short human-readable label for the task watch.".to_string(),
            )),
        ),
        (
            "objective".to_string(),
            JsonSchema::string(Some(
                "Human-readable objective the agent should periodically reevaluate.".to_string(),
            )),
        ),
        (
            "prompt".to_string(),
            JsonSchema::string(Some(
                "Follow-up prompt injected into the thread each time the task watch becomes due."
                    .to_string(),
            )),
        ),
        (
            "check_every_seconds".to_string(),
            JsonSchema::number(Some(
                "Recurring interval in seconds between reevaluation checks.".to_string(),
            )),
        ),
        (
            "initial_delay_seconds".to_string(),
            JsonSchema::number(Some(
                "Optional delay in seconds before the first check. Defaults to one full interval."
                    .to_string(),
            )),
        ),
        (
            "thread_id".to_string(),
            JsonSchema::string(Some(
                "Optional thread/session id to wake. Defaults to the current thread.".to_string(),
            )),
        ),
        (
            "max_checks".to_string(),
            JsonSchema::number(Some(
                "Optional cap on how many checks may run before the task watch auto-stops."
                    .to_string(),
            )),
        ),
        (
            "requires_response".to_string(),
            JsonSchema::boolean(Some(
                "Whether the deferred wake should expect a concrete response.".to_string(),
            )),
        ),
    ]);

    ToolSpec::Function(ResponsesApiTool {
        name: "watch_task_periodically".to_string(),
        description: "Registers a persisted task watch that periodically wakes the thread to reevaluate a concrete task. Use this for time-based \"check on this later\" work."
            .to_string(),
        strict: false,
        defer_loading: None,
        parameters: JsonSchema::object(
            properties,
            Some(vec![
                "title".to_string(),
                "objective".to_string(),
                "prompt".to_string(),
                "check_every_seconds".to_string(),
            ]),
            Some(false.into()),
        ),
        output_schema: None,
    })
}

pub fn create_list_task_watches_tool() -> ToolSpec {
    let properties = BTreeMap::from([(
        "thread_id".to_string(),
        JsonSchema::string(Some(
            "Optional thread/session id filter. Defaults to the current thread.".to_string(),
        )),
    )]);

    ToolSpec::Function(ResponsesApiTool {
        name: "list_task_watches".to_string(),
        description: "List persisted periodic task watches for the current or specified thread."
            .to_string(),
        strict: false,
        defer_loading: None,
        parameters: JsonSchema::object(properties, Some(Vec::new()), Some(false.into())),
        output_schema: None,
    })
}

pub fn create_update_task_watch_tool() -> ToolSpec {
    let properties = BTreeMap::from([
        (
            "task_watch_id".to_string(),
            JsonSchema::string(Some("Task watch id to update.".to_string())),
        ),
        (
            "action".to_string(),
            JsonSchema::string(Some(
                "Update action: `continue`, `backoff`, `snooze`, `complete`, or `stop`."
                    .to_string(),
            )),
        ),
        (
            "check_every_seconds".to_string(),
            JsonSchema::number(Some(
                "Optional new recurring cadence in seconds. Useful for `continue` or `backoff`."
                    .to_string(),
            )),
        ),
        (
            "delay_seconds".to_string(),
            JsonSchema::number(Some(
                "Optional one-off delay in seconds before the next check. Useful for `snooze`."
                    .to_string(),
            )),
        ),
        (
            "max_checks".to_string(),
            JsonSchema::number(Some("Optional new max-check cap.".to_string())),
        ),
        (
            "decision".to_string(),
            JsonSchema::string(Some("Optional short persisted decision label.".to_string())),
        ),
        (
            "observation".to_string(),
            JsonSchema::string(Some(
                "Optional short persisted observation summary.".to_string(),
            )),
        ),
    ]);

    ToolSpec::Function(ResponsesApiTool {
        name: "update_task_watch".to_string(),
        description: "Updates an existing task watch in place: continue, back off, snooze, complete, or stop it."
            .to_string(),
        strict: false,
        defer_loading: None,
        parameters: JsonSchema::object(
            properties,
            Some(vec!["task_watch_id".to_string(), "action".to_string()]),
            Some(false.into()),
        ),
        output_schema: None,
    })
}

pub fn create_cancel_task_watch_tool() -> ToolSpec {
    let properties = BTreeMap::from([(
        "task_watch_id".to_string(),
        JsonSchema::string(Some("Task watch id to stop.".to_string())),
    )]);

    ToolSpec::Function(ResponsesApiTool {
        name: "cancel_task_watch".to_string(),
        description: "Stops a persisted task watch so it will no longer wake the thread."
            .to_string(),
        strict: false,
        defer_loading: None,
        parameters: JsonSchema::object(
            properties,
            Some(vec!["task_watch_id".to_string()]),
            Some(false.into()),
        ),
        output_schema: None,
    })
}

pub fn create_write_stdin_tool() -> ToolSpec {
    let properties = BTreeMap::from([
        (
            "session_id".to_string(),
            JsonSchema::number(Some(
                "Identifier of the running unified exec session.".to_string(),
            )),
        ),
        (
            "chars".to_string(),
            JsonSchema::string(Some(
                "Bytes to write to stdin. Defaults to empty, which polls without writing.".to_string(),
            )),
        ),
        (
            "yield_time_ms".to_string(),
            JsonSchema::number(Some(
                "Wait before yielding output. Non-empty writes default to 250 ms and cap at 30000 ms; empty polls wait 5000-300000 ms by default.".to_string(),
            )),
        ),
        (
            "max_output_tokens".to_string(),
            JsonSchema::number(Some(
                "Output token budget. Defaults to 10000 tokens; larger requests may be capped by policy.".to_string(),
            )),
        ),
    ]);

    ToolSpec::Function(ResponsesApiTool {
        name: "write_stdin".to_string(),
        description:
            "Writes characters to an existing unified exec session and returns recent output."
                .to_string(),
        strict: false,
        defer_loading: None,
        parameters: JsonSchema::object(
            properties,
            Some(vec!["session_id".to_string()]),
            Some(false.into()),
        ),
        output_schema: Some(unified_exec_output_schema()),
    })
}

pub fn create_shell_command_tool(options: CommandToolOptions) -> ToolSpec {
    let mut properties = BTreeMap::from([
        (
            "command".to_string(),
            JsonSchema::string(Some(
                "Shell script to run in the user's default shell.".to_string(),
            )),
        ),
        (
            "workdir".to_string(),
            JsonSchema::string(Some(
                "Working directory for the command. Defaults to the turn cwd.".to_string(),
            )),
        ),
        (
            "timeout_ms".to_string(),
            JsonSchema::number(Some(
                "Maximum command runtime. Defaults to 10000 ms.".to_string(),
            )),
        ),
    ]);
    if options.allow_login_shell {
        properties.insert(
            "login".to_string(),
            JsonSchema::boolean(Some(
                "True runs with login shell semantics; false disables them. Defaults to true."
                    .to_string(),
            )),
        );
    }
    properties.extend(create_approval_parameters(
        options.exec_permission_approvals_enabled,
    ));

    let description = if cfg!(windows) {
        format!(
            r#"Runs a Powershell command (Windows) and returns its output.

Examples of valid command strings:

- ls -a (show hidden): "Get-ChildItem -Force"
- recursive find by name: "Get-ChildItem -Recurse -Filter *.py"
- recursive grep: "Get-ChildItem -Path C:\\myrepo -Recurse | Select-String -Pattern 'TODO' -CaseSensitive"
- ps aux | grep python: "Get-Process | Where-Object {{ $_.ProcessName -like '*python*' }}"
- setting an env var: "$env:FOO='bar'; echo $env:FOO"
- running an inline Python script: "@'\\nprint('Hello, world!')\\n'@ | python -"

{}"#,
            windows_shell_guidance()
        )
    } else {
        r#"Runs a shell command and returns its output.
- Always set the `workdir` param when using the shell_command function. Do not use `cd` unless absolutely necessary."#
            .to_string()
    };

    ToolSpec::Function(ResponsesApiTool {
        name: "shell_command".to_string(),
        description,
        strict: false,
        defer_loading: None,
        parameters: JsonSchema::object(
            properties,
            Some(vec!["command".to_string()]),
            Some(false.into()),
        ),
        output_schema: None,
    })
}

pub fn create_request_permissions_tool(description: String) -> ToolSpec {
    let properties = BTreeMap::from([
        (
            "reason".to_string(),
            JsonSchema::string(Some(
                "Optional short explanation for why additional permissions are needed.".to_string(),
            )),
        ),
        ("permissions".to_string(), permission_profile_schema()),
    ]);

    ToolSpec::Function(ResponsesApiTool {
        name: "request_permissions".to_string(),
        description,
        strict: false,
        defer_loading: None,
        parameters: JsonSchema::object(
            properties,
            Some(vec!["permissions".to_string()]),
            Some(false.into()),
        ),
        output_schema: None,
    })
}

pub fn request_permissions_tool_description() -> String {
    "Request additional filesystem or network permissions from the user and wait for the client to grant a subset of the requested permission profile. Granted permissions apply automatically to later shell-like commands in the current turn, or for the rest of the session if the client approves them at session scope."
        .to_string()
}

fn unified_exec_output_schema() -> Value {
    json!({
        "type": "object",
        "properties": {
            "chunk_id": {
                "type": "string",
                "description": "Chunk identifier included when the response reports one."
            },
            "wall_time_seconds": {
                "type": "number",
                "description": "Elapsed wall time spent waiting for output in seconds."
            },
            "exit_code": {
                "type": "number",
                "description": "Process exit code when the command finished during this call."
            },
            "session_id": {
                "type": "number",
                "description": "Session identifier to pass to write_stdin when the process is still running."
            },
            "original_token_count": {
                "type": "number",
                "description": "Approximate token count before output truncation."
            },
            "output": {
                "type": "string",
                "description": "Command output text, possibly truncated."
            }
        },
        "required": ["wall_time_seconds", "output"],
        "additionalProperties": false
    })
}

fn create_approval_parameters(
    exec_permission_approvals_enabled: bool,
) -> BTreeMap<String, JsonSchema> {
    let mut sandbox_permission_values = vec![json!("use_default")];
    if exec_permission_approvals_enabled {
        sandbox_permission_values.push(json!("with_additional_permissions"));
    }
    sandbox_permission_values.push(json!("require_escalated"));
    let sandbox_permissions_description = if exec_permission_approvals_enabled {
        "Per-command sandbox override. Defaults to `use_default`; use `with_additional_permissions` with `additional_permissions`, or `require_escalated` for unsandboxed execution."
    } else {
        "Per-command sandbox override. Defaults to `use_default`; use `require_escalated` for unsandboxed execution."
    };

    let mut properties = BTreeMap::from([
        (
            "sandbox_permissions".to_string(),
            JsonSchema::string_enum(
                sandbox_permission_values,
                Some(sandbox_permissions_description.to_string()),
            ),
        ),
        (
            "justification".to_string(),
            JsonSchema::string(Some(
                "User-facing approval question for `require_escalated`; omit otherwise.".to_string(),
            )),
        ),
        (
            "prefix_rule".to_string(),
            JsonSchema::array(JsonSchema::string(/*description*/ None), Some(
                    r#"Reusable approval prefix for `cmd`, only with `sandbox_permissions: "require_escalated"`; for example ["git", "pull"]."#.to_string(),
                )),
        ),
    ]);

    if exec_permission_approvals_enabled {
        let mut additional_permissions = permission_profile_schema();
        additional_permissions.description = Some(
            "Sandboxed filesystem or network access for this command; only with `sandbox_permissions: \"with_additional_permissions\"`."
                .to_string(),
        );
        properties.insert("additional_permissions".to_string(), additional_permissions);
    }

    properties
}

fn permission_profile_schema() -> JsonSchema {
    let mut schema = JsonSchema::object(
        BTreeMap::from([
            ("network".to_string(), network_permissions_schema()),
            ("file_system".to_string(), file_system_permissions_schema()),
        ]),
        /*required*/ None,
        Some(false.into()),
    );
    schema.description = Some("Filesystem or network access request.".to_string());
    schema
}

fn network_permissions_schema() -> JsonSchema {
    let mut schema = JsonSchema::object(
        BTreeMap::from([(
            "enabled".to_string(),
            JsonSchema::boolean(Some(
                "True requests network access; false or omitted requests none.".to_string(),
            )),
        )]),
        /*required*/ None,
        Some(false.into()),
    );
    schema.description = Some("Network access request.".to_string());
    schema
}

fn file_system_permissions_schema() -> JsonSchema {
    let mut schema = JsonSchema::object(
        BTreeMap::from([
            (
                "read".to_string(),
                JsonSchema::array(
                    JsonSchema::string(/*description*/ None),
                    Some(
                        "Absolute paths to grant read access; omit when none are needed."
                            .to_string(),
                    ),
                ),
            ),
            (
                "write".to_string(),
                JsonSchema::array(
                    JsonSchema::string(/*description*/ None),
                    Some(
                        "Absolute paths to grant write access; omit when none are needed."
                            .to_string(),
                    ),
                ),
            ),
        ]),
        /*required*/ None,
        Some(false.into()),
    );
    schema.description = Some("Filesystem access request.".to_string());
    schema
}

fn windows_shell_guidance() -> &'static str {
    r#"Windows safety rules:
- Do not compose destructive filesystem commands across shells. Do not enumerate paths in PowerShell and then pass them to `cmd /c`, batch builtins, or another shell for deletion or moving. Use one shell end-to-end, prefer native PowerShell cmdlets such as `Remove-Item` / `Move-Item` with `-LiteralPath`, and avoid string-built shell commands for file operations.
- Before any recursive delete or move on Windows, verify the resolved absolute target paths stay within the intended workspace or explicitly named target directory. Never issue a recursive delete or move against a computed path if the final target has not been checked.
- When using `Start-Process` to launch a background helper or service, pass `-WindowStyle Hidden` unless the user explicitly asked for a visible interactive window. Use visible windows only for interactive tools the user needs to see or control."#
}

#[cfg(test)]
#[path = "shell_spec_tests.rs"]
mod tests;
