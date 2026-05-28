use ac_protocol::{
    AgentKind, ArtifactKind, PlanStep, ResponsibilityStage, RunId, RunProjection, StepFailureKind,
    StepId,
};
use async_trait::async_trait;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Duration;
use tempfile::NamedTempFile;
use thiserror::Error;
use tokio::process::Command;
use tokio::time::sleep;
use tokio_util::sync::CancellationToken;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum MockScenario {
    HappyPath,
    FailOnExecute,
    TimeoutOnExecute,
}

#[derive(Debug, Clone)]
pub struct AgentExecutionRequest {
    pub workspace: PathBuf,
    pub run_id: RunId,
    pub task: String,
    pub step: PlanStep,
    pub projection: RunProjection,
    pub mock_scenario: Option<MockScenario>,
    pub cancel: CancellationToken,
}

#[derive(Debug, Clone)]
pub struct AdapterArtifact {
    pub kind: ArtifactKind,
    pub label: String,
    pub path: Option<String>,
    pub preview: Option<String>,
}

#[derive(Debug, Clone)]
pub enum AdapterOutcome {
    Completed {
        summary: String,
        artifact: Option<AdapterArtifact>,
    },
    Failed {
        kind: StepFailureKind,
        reason: String,
    },
}

#[derive(Debug, Error)]
pub enum AdapterError {
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
    #[error("json parse error: {0}")]
    Json(#[from] serde_json::Error),
    #[error("adapter interrupted")]
    Interrupted,
    #[error("adapter process failed: {command} ({code:?}): {stderr}")]
    ProcessFailed {
        command: String,
        code: Option<i32>,
        stderr: String,
    },
    #[error("adapter output was empty")]
    EmptyOutput,
}

#[async_trait]
pub trait AgentAdapter: Send + Sync {
    fn kind(&self) -> AgentKind;
    async fn execute(&self, request: AgentExecutionRequest) -> Result<AdapterOutcome, AdapterError>;
}

#[derive(Clone, Default)]
pub struct AdapterRegistry {
    entries: HashMap<AgentKind, Arc<dyn AgentAdapter>>,
}

impl AdapterRegistry {
    pub fn new() -> Self {
        let mut registry = Self::default();
        registry.insert(MockAdapter::default());
        registry.insert(CliAgentAdapter::codex());
        registry.insert(CliAgentAdapter::claude());
        registry.insert(CliAgentAdapter::gemini());
        registry
    }

    pub fn insert<A>(&mut self, adapter: A)
    where
        A: AgentAdapter + 'static,
    {
        self.entries.insert(adapter.kind(), Arc::new(adapter));
    }

    pub fn get(&self, kind: &AgentKind) -> Option<Arc<dyn AgentAdapter>> {
        self.entries.get(kind).cloned()
    }

    pub fn available(&self) -> Vec<AgentKind> {
        let mut values = self.entries.keys().cloned().collect::<Vec<_>>();
        values.sort();
        values
    }
}

#[derive(Clone, Default)]
pub struct MockAdapter;

#[async_trait]
impl AgentAdapter for MockAdapter {
    fn kind(&self) -> AgentKind {
        AgentKind::Mock
    }

    async fn execute(&self, request: AgentExecutionRequest) -> Result<AdapterOutcome, AdapterError> {
        let scenario = request.mock_scenario.unwrap_or(MockScenario::HappyPath);
        if matches!(scenario, MockScenario::TimeoutOnExecute)
            && request.step.stage == ResponsibilityStage::Execute
        {
            tokio::select! {
                _ = request.cancel.cancelled() => Err(AdapterError::Interrupted),
                _ = sleep(Duration::from_secs(5)) => Ok(AdapterOutcome::Completed {
                    summary: format!("mock {} eventually completed {}", request.run_id, request.step.id),
                    artifact: None,
                }),
            }
        } else if matches!(scenario, MockScenario::FailOnExecute)
            && request.step.stage == ResponsibilityStage::Execute
        {
            Ok(AdapterOutcome::Failed {
                kind: StepFailureKind::MockFailure,
                reason: format!("mock failure for {}", request.step.id),
            })
        } else {
            tokio::select! {
                _ = request.cancel.cancelled() => Err(AdapterError::Interrupted),
                _ = sleep(Duration::from_millis(40)) => Ok(AdapterOutcome::Completed {
                    summary: format!("mock completed {} for {}", request.step.id, request.task),
                    artifact: Some(AdapterArtifact {
                        kind: ArtifactKind::RunSummary,
                        label: format!("Mock artifact {}", request.step.id),
                        path: None,
                        preview: Some(format!("mock:{}:{}", request.run_id, request.step.id)),
                    }),
                }),
            }
        }
    }
}

#[derive(Debug, Clone)]
enum CliFlavor {
    Codex,
    Claude,
    Gemini,
}

#[derive(Debug, Clone)]
pub struct CliAgentAdapter {
    kind: AgentKind,
    flavor: CliFlavor,
}

impl CliAgentAdapter {
    pub fn codex() -> Self {
        Self {
            kind: AgentKind::Codex,
            flavor: CliFlavor::Codex,
        }
    }

    pub fn claude() -> Self {
        Self {
            kind: AgentKind::ClaudeCode,
            flavor: CliFlavor::Claude,
        }
    }

    pub fn gemini() -> Self {
        Self {
            kind: AgentKind::GeminiCli,
            flavor: CliFlavor::Gemini,
        }
    }
}

#[async_trait]
impl AgentAdapter for CliAgentAdapter {
    fn kind(&self) -> AgentKind {
        self.kind.clone()
    }

    async fn execute(&self, request: AgentExecutionRequest) -> Result<AdapterOutcome, AdapterError> {
        let prompt = build_prompt(&self.kind, &request);
        let summary = match self.flavor {
            CliFlavor::Codex => run_codex(request.workspace.as_path(), &prompt, request.cancel).await?,
            CliFlavor::Claude => {
                run_claude(request.workspace.as_path(), &prompt, request.cancel).await?
            }
            CliFlavor::Gemini => {
                run_gemini(request.workspace.as_path(), &prompt, request.cancel).await?
            }
        };

        Ok(AdapterOutcome::Completed {
            summary: summary.clone(),
            artifact: Some(AdapterArtifact {
                kind: ArtifactKind::Report,
                label: format!("{:?} {}", self.kind, request.step.id),
                path: None,
                preview: Some(summary),
            }),
        })
    }
}

fn build_prompt(agent: &AgentKind, request: &AgentExecutionRequest) -> String {
    let previous = request
        .projection
        .plan
        .as_ref()
        .map(|plan| {
            plan.steps
                .iter()
                .filter(|step| step.status == ac_protocol::StepStatus::Completed)
                .filter_map(|step| {
                    step.summary
                        .as_ref()
                        .map(|summary| format!("{}: {}", step.id.as_str(), summary))
                })
                .collect::<Vec<_>>()
                .join(" | ")
        })
        .filter(|text| !text.is_empty())
        .unwrap_or_else(|| "none".to_owned());

    format!(
        "You are participating in an ai-collab daemon smoke run.\nReturn exactly one plain-text line that starts with SUMMARY: and contains no markdown.\nAgent: {:?}\nRun: {}\nTask: {}\nStep: {} ({:?})\nDone when: {}\nPrevious completed steps: {}\n",
        agent,
        request.run_id,
        request.task,
        request.step.id,
        request.step.stage,
        request.step.done_when,
        previous,
    )
}

async fn run_codex(
    workspace: &Path,
    prompt: &str,
    cancel: CancellationToken,
) -> Result<String, AdapterError> {
    let outfile = NamedTempFile::new()?;
    let path = outfile.path().to_path_buf();
    let mut child = Command::new("codex")
        .arg("exec")
        .arg("--skip-git-repo-check")
        .arg("--sandbox")
        .arg("read-only")
        .arg("--color")
        .arg("never")
        .arg("--ephemeral")
        .arg("-C")
        .arg(workspace)
        .arg("-o")
        .arg(&path)
        .arg(prompt)
        .spawn()?;

    let status = tokio::select! {
        _ = cancel.cancelled() => {
            let _ = child.kill().await;
            return Err(AdapterError::Interrupted);
        }
        status = child.wait() => status?,
    };

    if !status.success() {
        return Err(AdapterError::ProcessFailed {
            command: "codex".to_owned(),
            code: status.code(),
            stderr: String::new(),
        });
    }

    let raw = tokio::fs::read_to_string(path).await?;
    extract_summary(&raw)
}

async fn run_claude(
    workspace: &Path,
    prompt: &str,
    cancel: CancellationToken,
) -> Result<String, AdapterError> {
    let mut child = Command::new("claude")
        .arg("-p")
        .arg(prompt)
        .arg("--output-format")
        .arg("json")
        .arg("--permission-mode")
        .arg("bypassPermissions")
        .arg("--allowedTools")
        .arg("")
        .current_dir(workspace)
        .spawn()?;

    let output = tokio::select! {
        _ = cancel.cancelled() => {
            let _ = child.kill().await;
            return Err(AdapterError::Interrupted);
        }
        output = child.wait_with_output() => output?,
    };

    if !output.status.success() {
        return Err(AdapterError::ProcessFailed {
            command: "claude".to_owned(),
            code: output.status.code(),
            stderr: String::from_utf8_lossy(&output.stderr).trim().to_owned(),
        });
    }

    let value: Value = serde_json::from_slice(&output.stdout)?;
    let result = value
        .get("result")
        .and_then(|item| item.as_str())
        .unwrap_or_default()
        .to_owned();
    extract_summary(&result)
}

async fn run_gemini(
    workspace: &Path,
    prompt: &str,
    cancel: CancellationToken,
) -> Result<String, AdapterError> {
    let mut child = Command::new("gemini")
        .arg("-p")
        .arg(prompt)
        .arg("-o")
        .arg("text")
        .arg("--yolo")
        .current_dir(workspace)
        .spawn()?;

    let output = tokio::select! {
        _ = cancel.cancelled() => {
            let _ = child.kill().await;
            return Err(AdapterError::Interrupted);
        }
        output = child.wait_with_output() => output?,
    };

    if !output.status.success() {
        return Err(AdapterError::ProcessFailed {
            command: "gemini".to_owned(),
            code: output.status.code(),
            stderr: String::from_utf8_lossy(&output.stderr).trim().to_owned(),
        });
    }

    let stdout = String::from_utf8_lossy(&output.stdout).trim().to_owned();
    let stderr = String::from_utf8_lossy(&output.stderr).trim().to_owned();
    extract_summary(if stdout.is_empty() { &stderr } else { &stdout })
}

fn extract_summary(raw: &str) -> Result<String, AdapterError> {
    let line = raw
        .lines()
        .rev()
        .find_map(|line| line.trim().strip_prefix("SUMMARY:").map(str::trim))
        .map(str::to_owned)
        .or_else(|| raw.lines().rev().find(|line| !line.trim().is_empty()).map(|line| line.trim().to_owned()))
        .ok_or(AdapterError::EmptyOutput)?;

    if line.is_empty() {
        Err(AdapterError::EmptyOutput)
    } else {
        Ok(line)
    }
}

pub fn build_smoke_request(agent: AgentKind, workspace: impl Into<PathBuf>) -> AgentExecutionRequest {
    let step_id = match agent {
        AgentKind::GeminiCli => StepId::from("step-gemini"),
        AgentKind::ClaudeCode => StepId::from("step-claude"),
        _ => StepId::from("step-codex"),
    };
    AgentExecutionRequest {
        workspace: workspace.into(),
        run_id: RunId::from("run-real-smoke"),
        task: format!("Return a compact smoke summary for {:?}", agent),
        step: PlanStep {
            id: step_id,
            title: "Smoke".to_owned(),
            stage: ResponsibilityStage::Model,
            status: ac_protocol::StepStatus::Pending,
            assignee: None,
            done_when: "Return one stable summary line.".to_owned(),
            eta_minutes: Some(1),
            started_at: None,
            completed_at: None,
            summary: None,
            failure_kind: None,
            failure_reason: None,
        },
        projection: RunProjection {
            run: ac_protocol::RunMetadata {
                id: RunId::from("run-real-smoke"),
                workspace: ".".to_owned(),
                task: "Smoke".to_owned(),
                controller: agent.clone(),
                phase: ac_protocol::RunPhase::Running,
                created_at: chrono::Utc::now(),
                updated_at: chrono::Utc::now(),
            },
            plan: None,
            approvals: Vec::new(),
            artifacts: Vec::new(),
            event_count: 0,
            last_sequence: 0,
        },
        mock_scenario: None,
        cancel: CancellationToken::new(),
    }
}

