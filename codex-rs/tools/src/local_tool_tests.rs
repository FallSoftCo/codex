use super::*;
use pretty_assertions::assert_eq;
use std::collections::BTreeMap;

fn windows_shell_safety_description() -> String {
    format!("\n\n{}", windows_destructive_filesystem_guidance())
}

#[test]
fn shell_tool_matches_expected_spec() {
    let tool = create_shell_tool(ShellToolOptions {
        exec_permission_approvals_enabled: false,
    });

    let description = if cfg!(windows) {
        r#"Runs a Powershell command (Windows) and returns its output. Arguments to `shell` will be passed to CreateProcessW(). Most commands should be prefixed with ["powershell.exe", "-Command"].

Examples of valid command strings:

- ls -a (show hidden): ["powershell.exe", "-Command", "Get-ChildItem -Force"]
- recursive find by name: ["powershell.exe", "-Command", "Get-ChildItem -Recurse -Filter *.py"]
- recursive grep: ["powershell.exe", "-Command", "Get-ChildItem -Path C:\\myrepo -Recurse | Select-String -Pattern 'TODO' -CaseSensitive"]
- ps aux | grep python: ["powershell.exe", "-Command", "Get-Process | Where-Object { $_.ProcessName -like '*python*' }"]
- setting an env var: ["powershell.exe", "-Command", "$env:FOO='bar'; echo $env:FOO"]
- running an inline Python script: ["powershell.exe", "-Command", "@'\\nprint('Hello, world!')\\n'@ | python -"]"#
            .to_string()
            + &windows_shell_safety_description()
    } else {
        r#"Runs a shell command and returns its output.
- The arguments to `shell` will be passed to execvp(). Most terminal commands should be prefixed with ["bash", "-lc"].
- Always set the `workdir` param when using the shell function. Do not use `cd` unless absolutely necessary."#
            .to_string()
    };

    let properties = BTreeMap::from([
        (
            "command".to_string(),
            JsonSchema::array(JsonSchema::string(/*description*/ None), Some("The command to execute".to_string())),
        ),
        (
            "workdir".to_string(),
            JsonSchema::string(Some("The working directory to execute the command in".to_string())),
        ),
        (
            "timeout_ms".to_string(),
            JsonSchema::number(Some("The timeout for the command in milliseconds".to_string())),
        ),
        (
            "sandbox_permissions".to_string(),
            JsonSchema::string(Some(
                    "Sandbox permissions for the command. Set to \"require_escalated\" to request running without sandbox restrictions; defaults to \"use_default\"."
                        .to_string(),
                )),
        ),
        (
            "justification".to_string(),
            JsonSchema::string(Some(
                    r#"Only set if sandbox_permissions is \"require_escalated\".
                    Request approval from the user to run this command outside the sandbox.
                    Phrased as a simple question that summarizes the purpose of the
                    command as it relates to the task at hand - e.g. 'Do you want to
                    fetch and pull the latest version of this git branch?'"#
                        .to_string(),
                )),
        ),
        (
            "prefix_rule".to_string(),
            JsonSchema::array(JsonSchema::string(/*description*/ None), Some(
                    r#"Only specify when sandbox_permissions is `require_escalated`.
                        Suggest a prefix command pattern that will allow you to fulfill similar requests from the user in the future.
                        Should be a short but reasonable prefix, e.g. [\"git\", \"pull\"] or [\"uv\", \"run\"] or [\"pytest\"]."#
                        .to_string(),
                )),
        ),
    ]);

    assert_eq!(
        tool,
        ToolSpec::Function(ResponsesApiTool {
            name: "shell".to_string(),
            description,
            strict: false,
            defer_loading: None,
            parameters: JsonSchema::object(
                properties,
                Some(vec!["command".to_string()]),
                Some(false.into())
            ),
            output_schema: None,
        })
    );
}

#[test]
fn exec_command_tool_matches_expected_spec() {
    let tool = create_exec_command_tool(CommandToolOptions {
        allow_login_shell: true,
        exec_permission_approvals_enabled: false,
    });

    let description = if cfg!(windows) {
        format!(
            "Runs a command in a PTY, returning output or a session ID for ongoing interaction. Prefer `watch_process_exit` over long inline waits when you only need to react after the process finishes.{}",
            windows_shell_safety_description()
        )
    } else {
        "Runs a command in a PTY, returning output or a session ID for ongoing interaction. Prefer `watch_process_exit` over long inline waits when you only need to react after the process finishes.".to_string()
    };

    let mut properties = BTreeMap::from([
        (
            "cmd".to_string(),
            JsonSchema::string(Some("Shell command to execute.".to_string())),
        ),
        (
            "workdir".to_string(),
            JsonSchema::string(Some(
                    "Optional working directory to run the command in; defaults to the turn cwd."
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
                    "Whether to allocate a TTY for the command. Defaults to false (plain pipes); set to true to open a PTY and access TTY process."
                        .to_string(),
                )),
        ),
        (
            "yield_time_ms".to_string(),
            JsonSchema::number(Some(
                    "How long to wait (in milliseconds) for output before yielding.".to_string(),
                )),
        ),
        (
            "max_output_tokens".to_string(),
            JsonSchema::number(Some(
                    "Maximum number of tokens to return. Excess output will be truncated."
                        .to_string(),
                )),
        ),
        (
            "login".to_string(),
            JsonSchema::boolean(Some(
                    "Whether to run the shell with -l/-i semantics. Defaults to true.".to_string(),
                )),
        ),
    ]);
    properties.extend(create_approval_parameters(
        /*exec_permission_approvals_enabled*/ false,
    ));

    assert_eq!(
        tool,
        ToolSpec::Function(ResponsesApiTool {
            name: "exec_command".to_string(),
            description,
            strict: false,
            defer_loading: None,
            parameters: JsonSchema::object(
                properties,
                Some(vec!["cmd".to_string()]),
                Some(false.into())
            ),
            output_schema: Some(unified_exec_output_schema()),
        })
    );
}

#[test]
fn write_stdin_tool_matches_expected_spec() {
    let tool = create_write_stdin_tool();

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
                "Bytes to write to stdin (may be empty to poll).".to_string(),
            )),
        ),
        (
            "yield_time_ms".to_string(),
            JsonSchema::number(Some(
                "How long to wait (in milliseconds) for output before yielding.".to_string(),
            )),
        ),
        (
            "max_output_tokens".to_string(),
            JsonSchema::number(Some(
                "Maximum number of tokens to return. Excess output will be truncated.".to_string(),
            )),
        ),
    ]);

    assert_eq!(
        tool,
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
                Some(false.into())
            ),
            output_schema: Some(unified_exec_output_schema()),
        })
    );
}

#[test]
fn watch_agent_completion_tool_matches_expected_spec() {
    let tool = create_watch_agent_completion_tool();

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

    assert_eq!(
        tool,
        ToolSpec::Function(ResponsesApiTool {
            name: "watch_agent_completion".to_string(),
            description: "Registers a persisted watcher that wakes the thread when another agent reaches a target completion state. Prefer this over stretching `wait_agent` into a long-lived blocking wait.".to_string(),
            strict: false,
            defer_loading: None,
            parameters: JsonSchema::object(properties, Some(vec![
                    "target".to_string(),
                    "title".to_string(),
                    "prompt".to_string(),
                ]), Some(false.into()),),
            output_schema: None,
        })
    );
}

#[test]
fn watch_task_periodically_tool_matches_expected_spec() {
    let tool = create_watch_task_periodically_tool();

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

    assert_eq!(
        tool,
        ToolSpec::Function(ResponsesApiTool {
            name: "watch_task_periodically".to_string(),
            description: "Registers a persisted task watch that periodically wakes the thread to reevaluate a concrete task. Use this for time-based \"check on this later\" work.".to_string(),
            strict: false,
            defer_loading: None,
            parameters: JsonSchema::object(properties, Some(vec![
                    "title".to_string(),
                    "objective".to_string(),
                    "prompt".to_string(),
                    "check_every_seconds".to_string(),
                ]), Some(false.into()),),
            output_schema: None,
        })
    );
}

#[test]
fn shell_tool_with_request_permission_includes_additional_permissions() {
    let tool = create_shell_tool(ShellToolOptions {
        exec_permission_approvals_enabled: true,
    });

    let mut properties = BTreeMap::from([
        (
            "command".to_string(),
            JsonSchema::array(
                JsonSchema::string(/*description*/ None),
                Some("The command to execute".to_string()),
            ),
        ),
        (
            "workdir".to_string(),
            JsonSchema::string(Some(
                "The working directory to execute the command in".to_string(),
            )),
        ),
        (
            "timeout_ms".to_string(),
            JsonSchema::number(Some(
                "The timeout for the command in milliseconds".to_string(),
            )),
        ),
    ]);
    properties.extend(create_approval_parameters(
        /*exec_permission_approvals_enabled*/ true,
    ));

    let description = if cfg!(windows) {
        format!(
            r#"Runs a Powershell command (Windows) and returns its output. Arguments to `shell` will be passed to CreateProcessW(). Most commands should be prefixed with ["powershell.exe", "-Command"].

Examples of valid command strings:

- ls -a (show hidden): ["powershell.exe", "-Command", "Get-ChildItem -Force"]
- recursive find by name: ["powershell.exe", "-Command", "Get-ChildItem -Recurse -Filter *.py"]
- recursive grep: ["powershell.exe", "-Command", "Get-ChildItem -Path C:\\myrepo -Recurse | Select-String -Pattern 'TODO' -CaseSensitive"]
- ps aux | grep python: ["powershell.exe", "-Command", "Get-Process | Where-Object {{ $_.ProcessName -like '*python*' }}"]
- setting an env var: ["powershell.exe", "-Command", "$env:FOO='bar'; echo $env:FOO"]
- running an inline Python script: ["powershell.exe", "-Command", "@'\\nprint('Hello, world!')\\n'@ | python -"]

{}"#,
            windows_destructive_filesystem_guidance()
        )
    } else {
        r#"Runs a shell command and returns its output.
- The arguments to `shell` will be passed to execvp(). Most terminal commands should be prefixed with ["bash", "-lc"].
- Always set the `workdir` param when using the shell function. Do not use `cd` unless absolutely necessary."#
            .to_string()
    };

    assert_eq!(
        tool,
        ToolSpec::Function(ResponsesApiTool {
            name: "shell".to_string(),
            description,
            strict: false,
            defer_loading: None,
            parameters: JsonSchema::object(
                properties,
                Some(vec!["command".to_string()]),
                Some(false.into())
            ),
            output_schema: None,
        })
    );
}

#[test]
fn request_permissions_tool_includes_full_permission_schema() {
    let tool =
        create_request_permissions_tool("Request extra permissions for this turn.".to_string());

    let properties = BTreeMap::from([
        (
            "reason".to_string(),
            JsonSchema::string(Some(
                "Optional short explanation for why additional permissions are needed.".to_string(),
            )),
        ),
        ("permissions".to_string(), permission_profile_schema()),
    ]);

    assert_eq!(
        tool,
        ToolSpec::Function(ResponsesApiTool {
            name: "request_permissions".to_string(),
            description: "Request extra permissions for this turn.".to_string(),
            strict: false,
            defer_loading: None,
            parameters: JsonSchema::object(
                properties,
                Some(vec!["permissions".to_string()]),
                Some(false.into())
            ),
            output_schema: None,
        })
    );
}

#[test]
fn shell_command_tool_matches_expected_spec() {
    let tool = create_shell_command_tool(CommandToolOptions {
        allow_login_shell: true,
        exec_permission_approvals_enabled: false,
    });

    let description = if cfg!(windows) {
        r#"Runs a Powershell command (Windows) and returns its output.

Examples of valid command strings:

- ls -a (show hidden): "Get-ChildItem -Force"
- recursive find by name: "Get-ChildItem -Recurse -Filter *.py"
- recursive grep: "Get-ChildItem -Path C:\\myrepo -Recurse | Select-String -Pattern 'TODO' -CaseSensitive"
- ps aux | grep python: "Get-Process | Where-Object { $_.ProcessName -like '*python*' }"
- setting an env var: "$env:FOO='bar'; echo $env:FOO"
- running an inline Python script: "@'\\nprint('Hello, world!')\\n'@ | python -""#
            .to_string()
            + &windows_shell_safety_description()
    } else {
        r#"Runs a shell command and returns its output.
- Always set the `workdir` param when using the shell_command function. Do not use `cd` unless absolutely necessary."#
            .to_string()
    };

    let mut properties = BTreeMap::from([
        (
            "command".to_string(),
            JsonSchema::string(Some(
                "The shell script to execute in the user's default shell".to_string(),
            )),
        ),
        (
            "workdir".to_string(),
            JsonSchema::string(Some(
                "The working directory to execute the command in".to_string(),
            )),
        ),
        (
            "timeout_ms".to_string(),
            JsonSchema::number(Some(
                "The timeout for the command in milliseconds".to_string(),
            )),
        ),
        (
            "login".to_string(),
            JsonSchema::boolean(Some(
                "Whether to run the shell with login shell semantics. Defaults to true."
                    .to_string(),
            )),
        ),
    ]);
    properties.extend(create_approval_parameters(
        /*exec_permission_approvals_enabled*/ false,
    ));

    assert_eq!(
        tool,
        ToolSpec::Function(ResponsesApiTool {
            name: "shell_command".to_string(),
            description,
            strict: false,
            defer_loading: None,
            parameters: JsonSchema::object(
                properties,
                Some(vec!["command".to_string()]),
                Some(false.into())
            ),
            output_schema: None,
        })
    );
}
