use chrono::{DateTime, Utc};
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use std::fmt::{self, Display};

macro_rules! id_type {
    ($name:ident) => {
        #[derive(
            Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize, JsonSchema,
        )]
        #[serde(transparent)]
        pub struct $name(pub String);

        impl $name {
            pub fn new(value: impl Into<String>) -> Self {
                Self(value.into())
            }

            pub fn as_str(&self) -> &str {
                &self.0
            }
        }

        impl Display for $name {
            fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                self.0.fmt(f)
            }
        }

        impl From<&str> for $name {
            fn from(value: &str) -> Self {
                Self(value.to_owned())
            }
        }

        impl From<String> for $name {
            fn from(value: String) -> Self {
                Self(value)
            }
        }
    };
}

id_type!(RunId);
id_type!(PlanId);
id_type!(StepId);
id_type!(ApprovalId);
id_type!(ArtifactId);

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum AgentKind {
    Codex,
    ClaudeCode,
    GeminiCli,
    Mock,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum RunPhase {
    Created,
    Ready,
    Running,
    WaitingApproval,
    Completed,
    Failed,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum StepStatus {
    Pending,
    Running,
    Completed,
    Failed,
    Blocked,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum StepFailureKind {
    AdapterError,
    ApprovalDenied,
    Timeout,
    Interrupted,
    MockFailure,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum ResponsibilityStage {
    Collect,
    Model,
    Plan,
    Artifact,
    Execute,
    Validate,
    Correct,
    Deliver,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum ApprovalStatus {
    Pending,
    Approved,
    Denied,
    Expired,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum ApprovalDecision {
    Approve,
    Deny,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum ArtifactKind {
    PlanBundle,
    RunSummary,
    Report,
    Contract,
    Mockup,
    Skeleton,
    CodeChange,
    LogExcerpt,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
pub struct RunMetadata {
    pub id: RunId,
    pub workspace: String,
    pub task: String,
    pub controller: AgentKind,
    pub phase: RunPhase,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
pub struct PlanStep {
    pub id: StepId,
    pub title: String,
    pub stage: ResponsibilityStage,
    pub status: StepStatus,
    pub assignee: Option<AgentKind>,
    pub done_when: String,
    pub eta_minutes: Option<u32>,
    pub started_at: Option<DateTime<Utc>>,
    pub completed_at: Option<DateTime<Utc>>,
    pub summary: Option<String>,
    pub failure_kind: Option<StepFailureKind>,
    pub failure_reason: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
pub struct Plan {
    pub id: PlanId,
    pub version: u32,
    pub generated_at: DateTime<Utc>,
    pub steps: Vec<PlanStep>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
pub struct ApprovalRequest {
    pub id: ApprovalId,
    pub run_id: RunId,
    pub step_id: Option<StepId>,
    pub title: String,
    pub reason: String,
    pub scope: String,
    pub status: ApprovalStatus,
    pub created_at: DateTime<Utc>,
    pub responded_at: Option<DateTime<Utc>>,
    pub response_note: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
pub struct Artifact {
    pub id: ArtifactId,
    pub run_id: RunId,
    pub kind: ArtifactKind,
    pub label: String,
    pub path: Option<String>,
    pub preview: Option<String>,
    pub registered_at: DateTime<Utc>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
pub struct RunProjection {
    pub run: RunMetadata,
    pub plan: Option<Plan>,
    pub approvals: Vec<ApprovalRequest>,
    pub artifacts: Vec<Artifact>,
    pub event_count: usize,
    pub last_sequence: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum RunAction {
    CreateRun {
        run_id: RunId,
        workspace: String,
        task: String,
        controller: AgentKind,
    },
    GeneratePlan {
        run_id: RunId,
    },
    StartStep {
        run_id: RunId,
        step_id: StepId,
        agent: AgentKind,
    },
    CompleteStep {
        run_id: RunId,
        step_id: StepId,
        summary: Option<String>,
    },
    FailStep {
        run_id: RunId,
        step_id: StepId,
        kind: StepFailureKind,
        reason: String,
    },
    RetryStep {
        run_id: RunId,
        step_id: StepId,
    },
    RequestApproval {
        run_id: RunId,
        step_id: Option<StepId>,
        title: String,
        reason: String,
        scope: String,
    },
    RespondApproval {
        run_id: RunId,
        approval_id: ApprovalId,
        decision: ApprovalDecision,
        note: Option<String>,
    },
    RegisterArtifact {
        run_id: RunId,
        kind: ArtifactKind,
        label: String,
        path: Option<String>,
        preview: Option<String>,
    },
}

impl RunAction {
    pub fn run_id(&self) -> &RunId {
        match self {
            Self::CreateRun { run_id, .. }
            | Self::GeneratePlan { run_id }
            | Self::StartStep { run_id, .. }
            | Self::CompleteStep { run_id, .. }
            | Self::FailStep { run_id, .. }
            | Self::RetryStep { run_id, .. }
            | Self::RequestApproval { run_id, .. }
            | Self::RespondApproval { run_id, .. }
            | Self::RegisterArtifact { run_id, .. } => run_id,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum RunEvent {
    RunCreated {
        metadata: RunMetadata,
    },
    PlanGenerated {
        plan: Plan,
    },
    StepStarted {
        step_id: StepId,
        agent: AgentKind,
        started_at: DateTime<Utc>,
    },
    StepCompleted {
        step_id: StepId,
        completed_at: DateTime<Utc>,
        summary: Option<String>,
    },
    StepFailed {
        step_id: StepId,
        failed_at: DateTime<Utc>,
        kind: StepFailureKind,
        reason: String,
    },
    StepRetried {
        step_id: StepId,
        retried_at: DateTime<Utc>,
    },
    ApprovalRequested {
        approval: ApprovalRequest,
    },
    ApprovalResponded {
        approval_id: ApprovalId,
        decision: ApprovalDecision,
        responded_at: DateTime<Utc>,
        note: Option<String>,
    },
    ArtifactRegistered {
        artifact: Artifact,
    },
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
pub struct StoredRunEvent {
    pub sequence: u64,
    pub run_id: RunId,
    pub emitted_at: DateTime<Utc>,
    pub event: RunEvent,
}

#[cfg(test)]
mod tests {
    use super::*;
    use schemars::schema_for;

    #[test]
    fn run_action_roundtrip_is_stable() {
        let action = RunAction::CreateRun {
            run_id: RunId::from("run-001"),
            workspace: "/tmp/project".to_owned(),
            task: "Build a snake game".to_owned(),
            controller: AgentKind::Codex,
        };
        let json = serde_json::to_string(&action).expect("serialize action");
        let decoded: RunAction = serde_json::from_str(&json).expect("deserialize action");
        assert_eq!(decoded, action);
    }

    #[test]
    fn run_projection_schema_is_generatable() {
        let schema = schema_for!(RunProjection);
        assert_eq!(schema.schema.object.is_some(), true);
    }
}
