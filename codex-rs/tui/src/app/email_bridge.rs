use super::App;
use std::collections::HashMap;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

use aws_config::BehaviorVersion;
use aws_config::Region;
use aws_sdk_s3::Client as S3Client;
use aws_sdk_sesv2::Client as SesClient;
use base64::Engine as _;
use base64::engine::general_purpose::STANDARD as BASE64_STANDARD;
use chrono::DateTime;
use chrono::Duration as ChronoDuration;
use chrono::Utc;
use codex_app_server_protocol::ServerNotification;
use codex_app_server_protocol::ServerRequest;
use codex_app_server_protocol::ToolRequestUserInputParams;
use codex_app_server_protocol::ToolRequestUserInputQuestion;
use codex_config::types::EmailAwayModeOverride;
use codex_config::types::EmailConfig;
use codex_protocol::ThreadId;
use codex_protocol::user_input::UserInput;
use hmac::Hmac;
use hmac::Mac;
use mailparse::MailHeaderMap;
use rand::RngCore;
use serde::Deserialize;
use serde::Serialize;
use sha2::Sha256;

use crate::app_command::AppCommand;
use crate::app_server_session::AppServerSession;
use crate::app_server_session::ThreadSessionState;

type HmacSha256 = Hmac<Sha256>;

const TOKEN_TTL_DAYS: i64 = 7;
const MAX_PROCESSED_KEYS: usize = 512;
const MAX_TRACKED_TOKENS: usize = 256;

#[derive(Debug, Clone)]
pub(super) struct EmailThreadContext {
    pub(super) thread_id: ThreadId,
    pub(super) thread_label: String,
}

#[derive(Debug, Clone)]
pub(super) struct EmailStatusSnapshot {
    pub(super) thread_id: ThreadId,
    pub(super) thread_label: String,
    pub(super) active_turn_id: Option<String>,
}

#[derive(Debug, Clone)]
pub(super) struct EmailReplyAction {
    pub(super) thread_id: ThreadId,
    pub(super) thread_label: String,
    pub(super) sender: String,
    pub(super) token: String,
    pub(super) command: EmailReplyCommand,
}

#[derive(Debug, Clone)]
pub(super) enum EmailReplyCommand {
    Continue { text: String },
    Status,
    Stop,
}

#[derive(Debug, Clone)]
pub(super) struct EmailRequestPrompt {
    pub(super) thread_id: ThreadId,
    pub(super) thread_label: String,
    pub(super) prompt: String,
}

#[derive(Debug, Clone)]
struct PendingCompletionEmail {
    token: String,
    thread: EmailThreadContext,
    queued_at: Instant,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct PersistedEmailBridgeState {
    secret_base64: String,
    manual_mode: EmailAwayModeOverride,
    #[serde(default)]
    issued_tokens: Vec<PersistedIssuedToken>,
    #[serde(default)]
    processed_object_keys: Vec<String>,
}

impl Default for PersistedEmailBridgeState {
    fn default() -> Self {
        let mut secret = [0_u8; 32];
        rand::rng().fill_bytes(&mut secret);
        Self {
            secret_base64: BASE64_STANDARD.encode(secret),
            manual_mode: EmailAwayModeOverride::Auto,
            issued_tokens: Vec::new(),
            processed_object_keys: Vec::new(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct PersistedIssuedToken {
    token: String,
    thread_id: String,
    thread_label: String,
    issued_at: DateTime<Utc>,
    expires_at: DateTime<Utc>,
}

#[derive(Debug, Clone)]
struct IssuedToken {
    thread_id: ThreadId,
    thread_label: String,
    expires_at: DateTime<Utc>,
}

#[derive(Debug)]
struct IncomingEmail {
    sender: String,
    subject: String,
    text_body: String,
}

pub(super) struct EmailBridge {
    config: EmailConfig,
    ses_client: SesClient,
    s3_client: S3Client,
    terminal_focused: Arc<AtomicBool>,
    state_path: PathBuf,
    state: PersistedEmailBridgeState,
    issued_tokens: HashMap<String, IssuedToken>,
    pending_completion_emails: HashMap<ThreadId, PendingCompletionEmail>,
    last_local_activity: Instant,
}

impl EmailBridge {
    pub(super) async fn new(
        config: EmailConfig,
        codex_home: &Path,
        terminal_focused: Arc<AtomicBool>,
    ) -> Result<Self, String> {
        let shared_config = aws_config::defaults(BehaviorVersion::latest())
            .region(Region::new(config.ses.region.clone()))
            .load()
            .await;
        let ses_client = SesClient::new(&shared_config);
        let s3_client = S3Client::new(&shared_config);
        let state_dir = codex_home.join("losangelex");
        std::fs::create_dir_all(&state_dir)
            .map_err(|err| format!("failed to create email bridge state dir: {err}"))?;
        let state_path = state_dir.join("email-bridge-v1.json");
        let state_existed = state_path.exists();
        let mut state = load_persisted_state(state_path.as_path())?;
        if !state_existed {
            state.manual_mode = config.default_away_mode;
        }
        let issued_tokens = rebuild_issued_tokens(&state);

        Ok(Self {
            config,
            ses_client,
            s3_client,
            terminal_focused,
            state_path,
            state,
            issued_tokens,
            pending_completion_emails: HashMap::new(),
            last_local_activity: Instant::now(),
        })
    }

    pub(super) fn poll_interval(&self) -> Duration {
        Duration::from_secs(self.config.poll_interval_seconds)
    }

    pub(super) fn note_local_activity(&mut self) {
        self.last_local_activity = Instant::now();
        if matches!(self.state.manual_mode, EmailAwayModeOverride::Auto) && !self.is_away() {
            self.pending_completion_emails.clear();
        }
    }

    pub(super) async fn set_away_mode(
        &mut self,
        mode: EmailAwayModeOverride,
    ) -> Result<(), String> {
        self.state.manual_mode = mode;
        if !self.is_away() {
            self.pending_completion_emails.clear();
        }
        self.persist_state()
    }

    pub(super) fn away_mode(&self) -> EmailAwayModeOverride {
        self.state.manual_mode
    }

    pub(super) fn is_away(&self) -> bool {
        match self.state.manual_mode {
            EmailAwayModeOverride::Away => true,
            EmailAwayModeOverride::Present => false,
            EmailAwayModeOverride::Auto => {
                !self.terminal_focused.load(Ordering::Relaxed)
                    || (self.config.away_after_seconds > 0
                        && self.last_local_activity.elapsed()
                            >= Duration::from_secs(self.config.away_after_seconds))
            }
        }
    }

    pub(super) async fn queue_turn_completed(
        &mut self,
        thread: EmailThreadContext,
    ) -> Result<(), String> {
        if !self.config.notify_on_turn_completed || !self.is_away() {
            return Ok(());
        }

        let token = self.issue_token(&thread)?;
        self.pending_completion_emails.insert(
            thread.thread_id,
            PendingCompletionEmail {
                token,
                thread,
                queued_at: Instant::now(),
            },
        );
        Ok(())
    }

    pub(super) async fn flush_pending_completion_emails(&mut self) -> Result<(), String> {
        if !self.is_away() {
            self.pending_completion_emails.clear();
            return Ok(());
        }

        let ready = self
            .pending_completion_emails
            .iter()
            .filter(|(_, pending)| {
                pending.queued_at.elapsed()
                    >= Duration::from_secs(self.config.completion_debounce_seconds)
            })
            .map(|(thread_id, _)| *thread_id)
            .collect::<Vec<_>>();

        for thread_id in ready {
            if let Some(pending) = self.pending_completion_emails.remove(&thread_id) {
                let subject = format!(
                    "{} {} completed work [lx:{}]",
                    self.config.subject_prefix, pending.thread.thread_label, pending.token
                );
                let body = format!(
                    concat!(
                        "{} completed a turn and is idle.\n\n",
                        "Thread: {}\n",
                        "Thread ID: {}\n",
                        "Reply token: {}\n\n",
                        "Reply with plain text to continue this thread.\n",
                        "Reply with `status` for a status email.\n",
                        "Reply with `stop` to interrupt the active turn.\n"
                    ),
                    pending.thread.thread_label,
                    pending.thread.thread_label,
                    pending.thread.thread_id,
                    pending.token,
                );
                self.send_email(subject, body).await?;
            }
        }

        Ok(())
    }

    pub(super) async fn send_request_user_input_email(
        &mut self,
        prompt: EmailRequestPrompt,
    ) -> Result<(), String> {
        if !self.config.notify_on_request_user_input || !self.is_away() {
            return Ok(());
        }

        let token = self.issue_token(&EmailThreadContext {
            thread_id: prompt.thread_id,
            thread_label: prompt.thread_label.clone(),
        })?;
        let subject = format!(
            "{} {} needs attention [lx:{}]",
            self.config.subject_prefix, prompt.thread_label, token
        );
        let body = format!(
            concat!(
                "{} is waiting on structured input.\n\n",
                "{}\n\n",
                "Reply token: {}\n\n",
                "Email replies do not resolve structured prompts yet.\n",
                "Open Losangelex to answer this request directly.\n"
            ),
            prompt.thread_label, prompt.prompt, token
        );
        self.send_email(subject, body).await
    }

    pub(super) async fn send_reply_rejected_email(
        &mut self,
        thread: EmailThreadContext,
        reason: &str,
    ) -> Result<(), String> {
        let token = self.issue_token(&thread)?;
        let subject = format!(
            "{} {} reply rejected [lx:{}]",
            self.config.subject_prefix, thread.thread_label, token
        );
        let body = format!(
            concat!(
                "Losangelex could not apply your email command for {}.\n\n",
                "Reason: {}\n",
                "Thread ID: {}\n",
                "Reply token: {}\n\n",
                "Open Losangelex locally to inspect the thread, or reply again with updated instructions.\n"
            ),
            thread.thread_label, reason, thread.thread_id, token
        );
        self.send_email(subject, body).await
    }

    pub(super) async fn send_status_email(
        &mut self,
        status: EmailStatusSnapshot,
    ) -> Result<(), String> {
        let token = self.issue_token(&EmailThreadContext {
            thread_id: status.thread_id,
            thread_label: status.thread_label.clone(),
        })?;
        let status_text = if let Some(turn_id) = status.active_turn_id.as_deref() {
            format!("active (turn {turn_id})")
        } else {
            "idle".to_string()
        };
        let subject = format!(
            "{} {} status [lx:{}]",
            self.config.subject_prefix, status.thread_label, token
        );
        let body = format!(
            concat!(
                "Thread: {}\n",
                "Thread ID: {}\n",
                "Status: {}\n",
                "Reply token: {}\n\n",
                "Reply with plain text to continue this thread.\n",
                "Reply with `stop` to interrupt the active turn.\n"
            ),
            status.thread_label, status.thread_id, status_text, token
        );
        self.send_email(subject, body).await
    }

    pub(super) async fn poll_inbox(&mut self) -> Result<Vec<EmailReplyAction>, String> {
        let response = self
            .s3_client
            .list_objects_v2()
            .bucket(&self.config.ses.inbox_bucket)
            .prefix(&self.config.ses.inbox_prefix)
            .max_keys(25)
            .send()
            .await
            .map_err(|err| format!("failed to list inbound email objects: {err}"))?;

        let mut actions = Vec::new();
        for object in response.contents() {
            let Some(key) = object.key() else {
                continue;
            };
            if self
                .state
                .processed_object_keys
                .iter()
                .any(|processed| processed == key)
            {
                continue;
            }

            let raw_email = self.fetch_email_object(key).await?;
            match self.process_incoming_email(key, &raw_email).await {
                Ok(Some(action)) => actions.push(action),
                Ok(None) => {}
                Err(err) => {
                    tracing::warn!(key, error = %err, "failed to process inbound email");
                }
            }
            self.mark_processed_key(key);
            if self.config.delete_processed_inbound {
                self.delete_email_object(key).await?;
            }
        }

        Ok(actions)
    }

    async fn fetch_email_object(&self, key: &str) -> Result<Vec<u8>, String> {
        let object = self
            .s3_client
            .get_object()
            .bucket(&self.config.ses.inbox_bucket)
            .key(key)
            .send()
            .await
            .map_err(|err| format!("failed to fetch inbound email object {key}: {err}"))?;
        let bytes = object
            .body
            .collect()
            .await
            .map_err(|err| format!("failed to read inbound email object {key}: {err}"))?;
        Ok(bytes.into_bytes().to_vec())
    }

    async fn delete_email_object(&self, key: &str) -> Result<(), String> {
        self.s3_client
            .delete_object()
            .bucket(&self.config.ses.inbox_bucket)
            .key(key)
            .send()
            .await
            .map_err(|err| {
                format!("failed to delete processed inbound email object {key}: {err}")
            })?;
        Ok(())
    }

    async fn process_incoming_email(
        &mut self,
        _key: &str,
        raw_email: &[u8],
    ) -> Result<Option<EmailReplyAction>, String> {
        let incoming = parse_incoming_email(raw_email)?;
        let sender = incoming.sender.to_ascii_lowercase();
        if !self
            .config
            .allowed_reply_senders
            .iter()
            .any(|allowed| allowed == &sender)
        {
            return Ok(None);
        }

        let Some(token) = parse_subject_token(&incoming.subject) else {
            return Ok(None);
        };
        self.gc_expired_tokens();
        let Some(issued) = self.issued_tokens.get(&token) else {
            return Ok(None);
        };
        if issued.expires_at < Utc::now() {
            return Ok(None);
        }

        let body = normalize_reply_body(&incoming.text_body);
        if body.is_empty() {
            return Ok(None);
        }

        let command = parse_reply_command(&body);
        Ok(Some(EmailReplyAction {
            thread_id: issued.thread_id,
            thread_label: issued.thread_label.clone(),
            sender,
            token,
            command,
        }))
    }

    fn issue_token(&mut self, thread: &EmailThreadContext) -> Result<String, String> {
        self.gc_expired_tokens();
        let issued_at = Utc::now();
        let expires_at = issued_at + ChronoDuration::days(TOKEN_TTL_DAYS);
        let token = build_token(
            &self.state.secret_base64,
            thread.thread_id.to_string().as_str(),
            issued_at.timestamp(),
        )?;
        self.issued_tokens.insert(
            token.clone(),
            IssuedToken {
                thread_id: thread.thread_id,
                thread_label: thread.thread_label.clone(),
                expires_at,
            },
        );
        self.state.issued_tokens.push(PersistedIssuedToken {
            token: token.clone(),
            thread_id: thread.thread_id.to_string(),
            thread_label: thread.thread_label.clone(),
            issued_at,
            expires_at,
        });
        if self.state.issued_tokens.len() > MAX_TRACKED_TOKENS {
            let keep_from = self.state.issued_tokens.len() - MAX_TRACKED_TOKENS;
            self.state.issued_tokens.drain(0..keep_from);
        }
        self.persist_state()?;
        Ok(token)
    }

    fn gc_expired_tokens(&mut self) {
        let now = Utc::now();
        self.state
            .issued_tokens
            .retain(|token| token.expires_at >= now);
        self.issued_tokens
            .retain(|_, token| token.expires_at >= now);
    }

    fn mark_processed_key(&mut self, key: &str) {
        self.state.processed_object_keys.push(key.to_string());
        if self.state.processed_object_keys.len() > MAX_PROCESSED_KEYS {
            let keep_from = self.state.processed_object_keys.len() - MAX_PROCESSED_KEYS;
            self.state.processed_object_keys.drain(0..keep_from);
        }
        if let Err(err) = self.persist_state() {
            tracing::warn!(error = %err, "failed to persist email bridge state");
        }
    }

    fn persist_state(&self) -> Result<(), String> {
        let bytes = serde_json::to_vec_pretty(&self.state)
            .map_err(|err| format!("failed to serialize email bridge state: {err}"))?;
        std::fs::write(&self.state_path, bytes)
            .map_err(|err| format!("failed to write email bridge state: {err}"))
    }

    async fn send_email(&self, subject: String, body: String) -> Result<(), String> {
        use aws_sdk_sesv2::types::Body;
        use aws_sdk_sesv2::types::Content;
        use aws_sdk_sesv2::types::Destination;
        use aws_sdk_sesv2::types::EmailContent;
        use aws_sdk_sesv2::types::Message;

        let subject = Content::builder()
            .data(subject)
            .charset("UTF-8")
            .build()
            .map_err(|err| format!("failed to build SES subject: {err}"))?;
        let text = Content::builder()
            .data(body)
            .charset("UTF-8")
            .build()
            .map_err(|err| format!("failed to build SES body: {err}"))?;
        let destination = Destination::builder()
            .to_addresses(self.config.developer_email.clone())
            .build();
        let message = Message::builder()
            .subject(subject)
            .body(Body::builder().text(text).build())
            .build();
        let mut request = self
            .ses_client
            .send_email()
            .from_email_address(format!(
                "{} <{}>",
                self.config.ses.from_name, self.config.ses.from_email
            ))
            .reply_to_addresses(self.config.ses.reply_to_email.clone())
            .destination(destination)
            .content(EmailContent::builder().simple(message).build());
        if let Some(configuration_set) = self.config.ses.configuration_set.as_ref() {
            request = request.configuration_set_name(configuration_set);
        }
        request
            .send()
            .await
            .map_err(|err| format!("failed to send SES email: {err}"))?;
        Ok(())
    }
}

fn load_persisted_state(state_path: &Path) -> Result<PersistedEmailBridgeState, String> {
    if !state_path.exists() {
        return Ok(PersistedEmailBridgeState::default());
    }
    let bytes = std::fs::read(state_path)
        .map_err(|err| format!("failed to read email bridge state: {err}"))?;
    serde_json::from_slice(&bytes)
        .map_err(|err| format!("failed to parse email bridge state: {err}"))
}

fn rebuild_issued_tokens(state: &PersistedEmailBridgeState) -> HashMap<String, IssuedToken> {
    state
        .issued_tokens
        .iter()
        .filter_map(|issued| {
            ThreadId::from_string(&issued.thread_id)
                .ok()
                .map(|thread_id| {
                    (
                        issued.token.clone(),
                        IssuedToken {
                            thread_id,
                            thread_label: issued.thread_label.clone(),
                            expires_at: issued.expires_at,
                        },
                    )
                })
        })
        .collect()
}

fn build_token(secret_base64: &str, thread_id: &str, issued_at: i64) -> Result<String, String> {
    let secret = BASE64_STANDARD
        .decode(secret_base64)
        .map_err(|err| format!("failed to decode email bridge secret: {err}"))?;
    let mut mac = HmacSha256::new_from_slice(&secret)
        .map_err(|err| format!("failed to initialize email bridge token signer: {err}"))?;
    mac.update(format!("{thread_id}:{issued_at}").as_bytes());
    let bytes = mac.finalize().into_bytes();
    Ok(base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(&bytes[..9]))
}

fn parse_incoming_email(raw_email: &[u8]) -> Result<IncomingEmail, String> {
    let parsed = mailparse::parse_mail(raw_email)
        .map_err(|err| format!("failed to parse inbound email MIME: {err}"))?;
    let subject = parsed
        .headers
        .get_first_value("Subject")
        .unwrap_or_default();
    let from = parsed.headers.get_first_value("From").unwrap_or_default();
    let sender = extract_email_address(&from)
        .ok_or_else(|| "failed to parse sender email address".to_string())?;
    let text_body = extract_text_body(&parsed)?;
    Ok(IncomingEmail {
        sender,
        subject,
        text_body,
    })
}

fn extract_text_body(parsed: &mailparse::ParsedMail<'_>) -> Result<String, String> {
    if parsed.subparts.is_empty() {
        return parsed
            .get_body()
            .map_err(|err| format!("failed to decode inbound email body: {err}"));
    }

    for part in &parsed.subparts {
        if part.ctype.mimetype.eq_ignore_ascii_case("text/plain") {
            return part
                .get_body()
                .map_err(|err| format!("failed to decode inbound email text part: {err}"));
        }
    }

    parsed
        .subparts
        .first()
        .ok_or_else(|| "inbound email did not contain a readable body".to_string())?
        .get_body()
        .map_err(|err| format!("failed to decode fallback inbound email body: {err}"))
}

fn extract_email_address(header_value: &str) -> Option<String> {
    let trimmed = header_value.trim();
    if let Some((_, rest)) = trimmed.split_once('<') {
        return rest
            .split_once('>')
            .map(|(email, _)| email.trim().to_ascii_lowercase());
    }
    (!trimmed.is_empty()).then(|| trimmed.to_ascii_lowercase())
}

fn parse_subject_token(subject: &str) -> Option<String> {
    let token_marker = "[lx:";
    let token_start = subject.find(token_marker)? + token_marker.len();
    let token_rest = subject.get(token_start..)?;
    let token_end = token_rest.find(']')?;
    let token = token_rest.get(..token_end)?.trim();
    (!token.is_empty()).then(|| token.to_string())
}

fn normalize_reply_body(body: &str) -> String {
    let mut normalized = Vec::new();
    let mut saw_content = false;
    for line in body.lines() {
        let trimmed = line.trim_end();
        let lower = trimmed.to_ascii_lowercase();
        if trimmed.starts_with('>')
            || (saw_content && lower.starts_with("on ") && lower.contains(" wrote:"))
        {
            break;
        }
        normalized.push(trimmed);
        saw_content |= !trimmed.trim().is_empty();
    }
    while normalized
        .first()
        .is_some_and(|line| line.trim().is_empty())
    {
        normalized.remove(0);
    }
    while normalized.last().is_some_and(|line| line.trim().is_empty()) {
        normalized.pop();
    }
    normalized.join("\n")
}

fn parse_reply_command(body: &str) -> EmailReplyCommand {
    let trimmed = body.trim();
    let normalized = trimmed
        .strip_prefix("@losangelex")
        .map(str::trim)
        .unwrap_or(trimmed);
    let lowercase = normalized.to_ascii_lowercase();
    match lowercase.as_str() {
        "status" => EmailReplyCommand::Status,
        "stop" => EmailReplyCommand::Stop,
        command if command.starts_with("continue ") => EmailReplyCommand::Continue {
            text: normalized["continue ".len()..].trim().to_string(),
        },
        _ => EmailReplyCommand::Continue {
            text: normalized.to_string(),
        },
    }
}

fn email_away_mode_label(mode: EmailAwayModeOverride) -> &'static str {
    match mode {
        EmailAwayModeOverride::Auto => "auto",
        EmailAwayModeOverride::Away => "away",
        EmailAwayModeOverride::Present => "present",
    }
}

fn format_request_user_input_prompt(params: &ToolRequestUserInputParams) -> String {
    params
        .questions
        .iter()
        .map(format_request_user_input_question)
        .collect::<Vec<_>>()
        .join("\n\n")
}

fn format_request_user_input_question(question: &ToolRequestUserInputQuestion) -> String {
    let mut lines = vec![format!("{}: {}", question.header, question.question)];
    if let Some(options) = question.options.as_ref() {
        lines.extend(
            options
                .iter()
                .map(|option| format!("- {}: {}", option.label, option.description)),
        );
    }
    lines.join("\n")
}

impl App {
    pub(super) async fn handle_email_bridge_notification(
        &mut self,
        notification: &ServerNotification,
    ) {
        let ServerNotification::TurnCompleted(notification) = notification else {
            return;
        };
        let Ok(thread_id) = ThreadId::from_string(notification.thread_id.as_str()) else {
            tracing::warn!(
                thread_id = notification.thread_id,
                "ignoring email notification for invalid thread id"
            );
            return;
        };
        let thread = EmailThreadContext {
            thread_id,
            thread_label: self.thread_label(thread_id),
        };
        let Some(email_bridge) = self.email_bridge.as_mut() else {
            return;
        };
        if let Err(err) = email_bridge.queue_turn_completed(thread).await {
            tracing::warn!(error = %err, "failed to queue turn completion email");
        }
    }

    pub(super) async fn handle_email_bridge_request(&mut self, request: &ServerRequest) {
        let ServerRequest::ToolRequestUserInput { params, .. } = request else {
            return;
        };
        let Ok(thread_id) = ThreadId::from_string(params.thread_id.as_str()) else {
            tracing::warn!(
                thread_id = params.thread_id,
                "ignoring email request for invalid thread id"
            );
            return;
        };
        let prompt = EmailRequestPrompt {
            thread_id,
            thread_label: self.thread_label(thread_id),
            prompt: format_request_user_input_prompt(params),
        };
        let Some(email_bridge) = self.email_bridge.as_mut() else {
            return;
        };
        if let Err(err) = email_bridge.send_request_user_input_email(prompt).await {
            tracing::warn!(error = %err, "failed to send request_user_input email");
        }
    }

    pub(super) async fn handle_email_bridge_tick(
        &mut self,
        app_server: &mut AppServerSession,
    ) -> color_eyre::eyre::Result<()> {
        let actions = {
            let Some(email_bridge) = self.email_bridge.as_mut() else {
                return Ok(());
            };
            email_bridge
                .flush_pending_completion_emails()
                .await
                .map_err(|err| color_eyre::eyre::eyre!("{err}"))?;
            email_bridge
                .poll_inbox()
                .await
                .map_err(|err| color_eyre::eyre::eyre!("{err}"))?
        };
        for action in actions {
            self.execute_email_reply_action(app_server, action).await;
        }
        Ok(())
    }

    pub(super) async fn set_email_away_mode(&mut self, mode: EmailAwayModeOverride) {
        let status = if let Some(email_bridge) = self.email_bridge.as_mut() {
            match email_bridge.set_away_mode(mode).await {
                Ok(()) => Ok((
                    if email_bridge.is_away() {
                        "away"
                    } else {
                        "present"
                    },
                    email_bridge.config.developer_email.clone(),
                )),
                Err(err) => Err(err),
            }
        } else {
            self.chat_widget.add_info_message(
                "Email bridge is not enabled for this Losangelex profile.".to_string(),
                Some("Add an [email] section to ~/.codex/config.toml to enable SES notifications and replies.".to_string()),
            );
            return;
        };
        match status {
            Ok((effective_state, developer_email)) => {
                self.chat_widget.add_info_message(
                    format!(
                        "Email away mode set to {}. Effective state: {effective_state}.",
                        email_away_mode_label(mode)
                    ),
                    Some(format!(
                        "Notifications are sent to {developer_email} when Losangelex considers you away."
                    )),
                );
            }
            Err(err) => {
                self.chat_widget
                    .add_error_message(format!("Failed to update email away mode: {err}"));
            }
        }
    }

    pub(super) fn show_email_away_status(&mut self) {
        let status = if let Some(email_bridge) = self.email_bridge.as_ref() {
            Some((
                email_away_mode_label(email_bridge.away_mode()),
                if email_bridge.is_away() {
                    "away".to_string()
                } else {
                    "present".to_string()
                },
                email_bridge.config.developer_email.clone(),
                email_bridge.config.poll_interval_seconds,
                email_bridge.config.completion_debounce_seconds,
                email_bridge.config.away_after_seconds,
            ))
        } else {
            self.chat_widget.add_info_message(
                "Email bridge is not enabled for this Losangelex profile.".to_string(),
                Some("Add an [email] section to ~/.codex/config.toml to enable SES notifications and replies.".to_string()),
            );
            return;
        };
        let Some((
            mode_label,
            effective_state,
            developer_email,
            poll_interval_seconds,
            completion_debounce_seconds,
            away_after_seconds,
        )) = status
        else {
            return;
        };
        self.chat_widget.add_info_message(
            format!(
                "Email bridge is enabled. Mode: {mode_label}. Effective state: {effective_state}."
            ),
            Some(format!(
                "Recipient: {developer_email}. Poll interval: {poll_interval_seconds}s. Debounce: {completion_debounce_seconds}s. Idle timer: {away_after_seconds}s."
            )),
        );
    }

    async fn execute_email_reply_action(
        &mut self,
        app_server: &mut AppServerSession,
        action: EmailReplyAction,
    ) {
        tracing::info!(
            sender = action.sender,
            thread_id = %action.thread_id,
            token = action.token,
            "processing inbound email reply"
        );
        let thread = EmailThreadContext {
            thread_id: action.thread_id,
            thread_label: action.thread_label.clone(),
        };
        match action.command {
            EmailReplyCommand::Continue { text } => {
                let Some(op) = self.email_reply_user_turn(action.thread_id, text).await else {
                    self.reject_email_reply(
                        thread,
                        "This thread is not loaded in the current Losangelex session.".to_string(),
                    )
                    .await;
                    return;
                };
                match self
                    .submit_thread_op(app_server, action.thread_id, op)
                    .await
                {
                    Ok(()) => {
                        self.chat_widget.add_info_message(
                            format!(
                                "Accepted email reply from {} for {}.",
                                action.sender, action.thread_label
                            ),
                            /*hint*/ None,
                        );
                    }
                    Err(err) => {
                        self.reject_email_reply(
                            thread,
                            format!("Failed to submit the email reply: {err}"),
                        )
                        .await;
                    }
                }
            }
            EmailReplyCommand::Stop => match self
                .submit_thread_op(app_server, action.thread_id, AppCommand::interrupt())
                .await
            {
                Ok(()) => {
                    self.chat_widget.add_info_message(
                        format!(
                            "Accepted email stop request from {} for {}.",
                            action.sender, action.thread_label
                        ),
                        /*hint*/ None,
                    );
                }
                Err(err) => {
                    self.reject_email_reply(
                        thread,
                        format!("Failed to interrupt the thread: {err}"),
                    )
                    .await;
                }
            },
            EmailReplyCommand::Status => {
                let snapshot = EmailStatusSnapshot {
                    thread_id: action.thread_id,
                    thread_label: action.thread_label.clone(),
                    active_turn_id: self.active_turn_id_for_thread(action.thread_id).await,
                };
                let Some(email_bridge) = self.email_bridge.as_mut() else {
                    return;
                };
                let status_result = email_bridge.send_status_email(snapshot).await;
                if let Err(err) = status_result {
                    self.reject_email_reply(
                        thread,
                        format!("Failed to send the status email: {err}"),
                    )
                    .await;
                }
            }
        }
    }

    async fn email_reply_user_turn(&self, thread_id: ThreadId, text: String) -> Option<AppCommand> {
        let session = self.email_reply_session(thread_id).await?;
        Some(AppCommand::user_turn_with_approvals_reviewer(
            vec![UserInput::Text {
                text,
                text_elements: Vec::new(),
            }],
            session.cwd.to_path_buf(),
            session.approval_policy,
            Some(session.approvals_reviewer),
            session.sandbox_policy,
            session.model,
            session.reasoning_effort,
            /*summary*/ None,
            Some(session.service_tier),
            /*final_output_json_schema*/ None,
            /*collaboration_mode*/ None,
            /*personality*/ None,
        ))
    }

    async fn email_reply_session(&self, thread_id: ThreadId) -> Option<ThreadSessionState> {
        if self.primary_thread_id == Some(thread_id)
            && let Some(session) = self.primary_session_configured.clone()
        {
            return Some(session);
        }

        let channel = self.thread_event_channels.get(&thread_id)?;
        let store = channel.store.lock().await;
        store.session.clone()
    }

    async fn reject_email_reply(&mut self, thread: EmailThreadContext, reason: String) {
        if let Some(email_bridge) = self.email_bridge.as_mut()
            && let Err(err) = email_bridge
                .send_reply_rejected_email(thread.clone(), reason.as_str())
                .await
        {
            tracing::warn!(error = %err, "failed to send email reply rejection notice");
        }
        self.chat_widget.add_error_message(format!(
            "Email reply for {} was rejected: {}",
            thread.thread_label, reason
        ));
    }
}

#[cfg(test)]
mod tests {
    use super::EmailAwayModeOverride;
    use super::EmailReplyCommand;
    use super::email_away_mode_label;
    use super::format_request_user_input_prompt;
    use super::normalize_reply_body;
    use super::parse_reply_command;
    use super::parse_subject_token;
    use codex_app_server_protocol::ToolRequestUserInputOption;
    use codex_app_server_protocol::ToolRequestUserInputParams;
    use codex_app_server_protocol::ToolRequestUserInputQuestion;

    #[test]
    fn subject_token_parser_reads_lx_marker() {
        assert_eq!(
            parse_subject_token("[Losangelex] Agent completed [lx:abc123]"),
            Some("abc123".to_string())
        );
    }

    #[test]
    fn normalize_reply_body_stops_before_quoted_history() {
        let body = "please continue on this\n\nOn Thu, someone wrote:\n> quoted";
        assert_eq!(normalize_reply_body(body), "please continue on this");
    }

    #[test]
    fn reply_command_parser_recognizes_status_and_stop() {
        assert!(matches!(
            parse_reply_command("status"),
            EmailReplyCommand::Status
        ));
        assert!(matches!(
            parse_reply_command("stop"),
            EmailReplyCommand::Stop
        ));
        assert!(matches!(
            parse_reply_command("continue working"),
            EmailReplyCommand::Continue { .. }
        ));
        assert!(matches!(
            parse_reply_command("@losangelex status"),
            EmailReplyCommand::Status
        ));
        assert!(matches!(
            parse_reply_command("@losangelex continue keep going"),
            EmailReplyCommand::Continue { text } if text == "keep going"
        ));
    }

    #[test]
    fn away_mode_labels_are_stable() {
        assert_eq!(email_away_mode_label(EmailAwayModeOverride::Auto), "auto");
        assert_eq!(email_away_mode_label(EmailAwayModeOverride::Away), "away");
        assert_eq!(
            email_away_mode_label(EmailAwayModeOverride::Present),
            "present"
        );
    }

    #[test]
    fn request_user_input_prompt_formats_questions_and_options() {
        let params = ToolRequestUserInputParams {
            thread_id: "thread-1".to_string(),
            turn_id: "turn-1".to_string(),
            item_id: "item-1".to_string(),
            questions: vec![ToolRequestUserInputQuestion {
                id: "focus".to_string(),
                header: "Focus".to_string(),
                question: "Which task should continue?".to_string(),
                is_other: false,
                is_secret: false,
                options: Some(vec![ToolRequestUserInputOption {
                    label: "Realtime".to_string(),
                    description: "Continue the realtime merge work".to_string(),
                }]),
            }],
        };

        assert_eq!(
            format_request_user_input_prompt(&params),
            "Focus: Which task should continue?\n- Realtime: Continue the realtime merge work"
        );
    }
}
