use ac_core::{AggregateError, RunAggregate};
use ac_protocol::{
    AgentKind, ApprovalDecision, ApprovalRequest, ApprovalStatus, Artifact, ArtifactKind, Plan,
    PlanId, PlanStep, ResponsibilityStage, RunAction, RunEvent, RunId, RunMetadata, RunPhase,
    RunProjection, StepFailureKind, StepId, StepStatus, StoredRunEvent,
};
use chrono::{DateTime, Duration, TimeZone, Utc};
use schemars::schema_for;
use serde_json::Value;
use std::collections::BTreeMap;
use std::sync::{Arc, Mutex};
use thiserror::Error;

pub trait Clock: Clone + Send + Sync + 'static {
    fn now(&self) -> DateTime<Utc>;
}

#[derive(Clone, Default)]
pub struct SystemClock;

impl Clock for SystemClock {
    fn now(&self) -> DateTime<Utc> {
        Utc::now()
    }
}

#[derive(Clone)]
pub struct SequencedClock {
    current: Arc<Mutex<DateTime<Utc>>>,
}

impl SequencedClock {
    pub fn new(start_at: DateTime<Utc>) -> Self {
        Self {
            current: Arc::new(Mutex::new(start_at)),
        }
    }
}

impl Clock for SequencedClock {
    fn now(&self) -> DateTime<Utc> {
        let mut guard = self.current.lock().expect("clock lock");
        let value = *guard;
        *guard = value + Duration::seconds(1);
        value
    }
}

#[derive(Debug, Error)]
pub enum EngineError {
    #[error("run aggregate is missing")]
    MissingAggregate,
    #[error("run already exists")]
    RunAlreadyExists,
    #[error("run id mismatch: expected {expected}, got {actual}")]
    RunIdMismatch { expected: RunId, actual: RunId },
    #[error("plan already exists")]
    PlanAlreadyExists,
    #[error("plan does not exist")]
    PlanMissing,
    #[error(transparent)]
    Aggregate(#[from] AggregateError),
}

#[derive(Debug, Clone)]
pub struct RunEngine<C: Clock = SystemClock> {
    clock: C,
}

impl Default for RunEngine<SystemClock> {
    fn default() -> Self {
        Self { clock: SystemClock }
    }
}

impl<C: Clock> RunEngine<C> {
    pub fn new(clock: C) -> Self {
        Self { clock }
    }

    pub fn handle_action(
        &self,
        current: Option<&RunAggregate>,
        action: RunAction,
    ) -> Result<Vec<RunEvent>, EngineError> {
        let run_id = action.run_id().clone();
        let now = self.clock.now();

        let candidate = match action {
            RunAction::CreateRun {
                run_id,
                workspace,
                task,
                controller,
            } => {
                if current.is_some() {
                    return Err(EngineError::RunAlreadyExists);
                }
                vec![RunEvent::RunCreated {
                    metadata: RunMetadata {
                        id: run_id,
                        workspace,
                        task,
                        controller,
                        phase: RunPhase::Created,
                        created_at: now,
                        updated_at: now,
                    },
                }]
            }
            RunAction::GeneratePlan { run_id: _ } => {
                let aggregate = self.require_matching_run(current, &run_id)?;
                if aggregate.plan().is_some() {
                    return Err(EngineError::PlanAlreadyExists);
                }
                let metadata = aggregate.metadata().ok_or(EngineError::MissingAggregate)?;
                vec![RunEvent::PlanGenerated {
                    plan: Self::default_plan(metadata, now),
                }]
            }
            RunAction::StartStep {
                run_id: _,
                step_id,
                agent,
            } => {
                self.require_matching_run(current, &run_id)?;
                vec![RunEvent::StepStarted {
                    step_id,
                    agent,
                    started_at: now,
                }]
            }
            RunAction::CompleteStep {
                run_id: _,
                step_id,
                summary,
            } => {
                self.require_matching_run(current, &run_id)?;
                vec![RunEvent::StepCompleted {
                    step_id,
                    completed_at: now,
                    summary,
                }]
            }
            RunAction::FailStep {
                run_id: _,
                step_id,
                kind,
                reason,
            } => {
                self.require_matching_run(current, &run_id)?;
                vec![RunEvent::StepFailed {
                    step_id,
                    failed_at: now,
                    kind,
                    reason,
                }]
            }
            RunAction::RetryStep { run_id: _, step_id } => {
                self.require_matching_run(current, &run_id)?;
                vec![RunEvent::StepRetried {
                    step_id,
                    retried_at: now,
                }]
            }
            RunAction::RequestApproval {
                run_id: _,
                step_id,
                title,
                reason,
                scope,
            } => {
                let aggregate = self.require_matching_run(current, &run_id)?;
                let approval_number = aggregate.approval_count() + 1;
                vec![RunEvent::ApprovalRequested {
                    approval: ApprovalRequest {
                        id: format!("approval-{approval_number:03}").into(),
                        run_id: run_id.clone(),
                        step_id,
                        title,
                        reason,
                        scope,
                        status: ApprovalStatus::Pending,
                        created_at: now,
                        responded_at: None,
                        response_note: None,
                    },
                }]
            }
            RunAction::RespondApproval {
                run_id: _,
                approval_id,
                decision,
                note,
            } => {
                self.require_matching_run(current, &run_id)?;
                vec![RunEvent::ApprovalResponded {
                    approval_id,
                    decision,
                    responded_at: now,
                    note,
                }]
            }
            RunAction::RegisterArtifact {
                run_id,
                kind,
                label,
                path,
                preview,
            } => {
                let aggregate = self.require_matching_run(current, &run_id)?;
                let artifact_number = aggregate.artifact_count() + 1;
                vec![RunEvent::ArtifactRegistered {
                    artifact: Artifact {
                        id: format!("artifact-{artifact_number:03}").into(),
                        run_id: run_id.clone(),
                        kind,
                        label,
                        path,
                        preview,
                        registered_at: now,
                    },
                }]
            }
        };

        self.validate_candidate(current, &run_id, &candidate)?;
        Ok(candidate)
    }

    fn require_matching_run<'a>(
        &self,
        current: Option<&'a RunAggregate>,
        run_id: &RunId,
    ) -> Result<&'a RunAggregate, EngineError> {
        let aggregate = current.ok_or(EngineError::MissingAggregate)?;
        let metadata = aggregate.metadata().ok_or(EngineError::MissingAggregate)?;
        if &metadata.id != run_id {
            return Err(EngineError::RunIdMismatch {
                expected: metadata.id.clone(),
                actual: run_id.clone(),
            });
        }
        Ok(aggregate)
    }

    fn validate_candidate(
        &self,
        current: Option<&RunAggregate>,
        run_id: &RunId,
        events: &[RunEvent],
    ) -> Result<(), EngineError> {
        let mut aggregate = current.cloned().unwrap_or_default();
        let mut sequence = aggregate.last_sequence();
        for event in events {
            sequence += 1;
            let envelope = StoredRunEvent {
                sequence,
                run_id: run_id.clone(),
                emitted_at: self.clock.now(),
                event: event.clone(),
            };
            aggregate.apply(&envelope)?;
        }
        Ok(())
    }

    fn default_plan(metadata: &RunMetadata, generated_at: DateTime<Utc>) -> Plan {
        Plan {
            id: PlanId::from("plan-001"),
            version: 1,
            generated_at,
            steps: vec![
                PlanStep {
                    id: StepId::from("step-001"),
                    title: format!("Collect current context for: {}", metadata.task),
                    stage: ResponsibilityStage::Collect,
                    status: StepStatus::Pending,
                    assignee: None,
                    done_when: format!(
                        "Confirm the current scope, constraints, and evidence needed for {}.",
                        metadata.task
                    ),
                    eta_minutes: Some(15),
                    started_at: None,
                    completed_at: None,
                    summary: None,
                    failure_kind: None,
                    failure_reason: None,
                },
                PlanStep {
                    id: StepId::from("step-002"),
                    title: format!("Build the first working iteration for: {}", metadata.task),
                    stage: ResponsibilityStage::Execute,
                    status: StepStatus::Pending,
                    assignee: None,
                    done_when: format!(
                        "Produce a first working implementation that directly advances {}.",
                        metadata.task
                    ),
                    eta_minutes: Some(45),
                    started_at: None,
                    completed_at: None,
                    summary: None,
                    failure_kind: None,
                    failure_reason: None,
                },
                PlanStep {
                    id: StepId::from("step-003"),
                    title: format!(
                        "Validate the first working iteration for: {}",
                        metadata.task
                    ),
                    stage: ResponsibilityStage::Validate,
                    status: StepStatus::Pending,
                    assignee: None,
                    done_when: format!(
                        "Verify the first working result for {} and record any follow-up risk.",
                        metadata.task
                    ),
                    eta_minutes: Some(20),
                    started_at: None,
                    completed_at: None,
                    summary: None,
                    failure_kind: None,
                    failure_reason: None,
                },
            ],
        }
    }
}

#[derive(Debug, Clone)]
pub struct ContractFixture {
    pub actions: Vec<RunAction>,
    pub events: Vec<StoredRunEvent>,
    pub projection: RunProjection,
}

pub fn p1_contract_schemas() -> BTreeMap<&'static str, Value> {
    let mut schemas = BTreeMap::new();
    schemas.insert(
        "run_action.schema.json",
        serde_json::to_value(schema_for!(RunAction)).expect("schema for action"),
    );
    schemas.insert(
        "stored_run_event.schema.json",
        serde_json::to_value(schema_for!(StoredRunEvent)).expect("schema for stored event"),
    );
    schemas.insert(
        "run_projection.schema.json",
        serde_json::to_value(schema_for!(RunProjection)).expect("schema for projection"),
    );
    schemas
}

pub fn build_p1_contract_fixture() -> Result<ContractFixture, EngineError> {
    let clock = SequencedClock::new(Utc.with_ymd_and_hms(2026, 4, 2, 9, 30, 0).unwrap());
    let engine = RunEngine::new(clock.clone());
    let actions = vec![
        RunAction::CreateRun {
            run_id: RunId::from("run-smoke-001"),
            workspace: "/workspace/demo".to_owned(),
            task: "Validate the Rust P0/P1 backend contract".to_owned(),
            controller: AgentKind::Codex,
        },
        RunAction::GeneratePlan {
            run_id: RunId::from("run-smoke-001"),
        },
        RunAction::StartStep {
            run_id: RunId::from("run-smoke-001"),
            step_id: StepId::from("step-001"),
            agent: AgentKind::Codex,
        },
        RunAction::CompleteStep {
            run_id: RunId::from("run-smoke-001"),
            step_id: StepId::from("step-001"),
            summary: Some("Collected the initial scope and constraints.".to_owned()),
        },
        RunAction::RequestApproval {
            run_id: RunId::from("run-smoke-001"),
            step_id: Some(StepId::from("step-002")),
            title: "Approve the first implementation pass".to_owned(),
            reason: "The next step writes the first working implementation.".to_owned(),
            scope: "workspace-write".to_owned(),
        },
        RunAction::RespondApproval {
            run_id: RunId::from("run-smoke-001"),
            approval_id: ac_protocol::ApprovalId::from("approval-001"),
            decision: ApprovalDecision::Approve,
            note: Some("Proceed with the first working implementation.".to_owned()),
        },
        RunAction::RegisterArtifact {
            run_id: RunId::from("run-smoke-001"),
            kind: ArtifactKind::RunSummary,
            label: "P1 contract summary".to_owned(),
            path: Some(".ai-collab/artifacts/run-smoke-001/summary.md".to_owned()),
            preview: Some("Run created, planned, stepped, approved, and persisted.".to_owned()),
        },
    ];

    let mut aggregate: Option<RunAggregate> = None;
    let mut stored_events = Vec::new();

    for action in &actions {
        let run_id = action.run_id().clone();
        let emitted = engine.handle_action(aggregate.as_ref(), action.clone())?;
        let mut next = aggregate.clone().unwrap_or_default();
        for event in emitted {
            let sequence = next.last_sequence() + 1;
            let envelope = StoredRunEvent {
                sequence,
                run_id: run_id.clone(),
                emitted_at: clock.now(),
                event,
            };
            next.apply(&envelope)?;
            stored_events.push(envelope);
        }
        aggregate = Some(next);
    }

    let projection = aggregate
        .ok_or(EngineError::MissingAggregate)?
        .projection()
        .map_err(EngineError::from)?;

    Ok(ContractFixture {
        actions,
        events: stored_events,
        projection,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn engine_can_progress_minimal_step_lifecycle() {
        let clock = SequencedClock::new(Utc.with_ymd_and_hms(2026, 4, 2, 0, 0, 0).unwrap());
        let engine = RunEngine::new(clock.clone());
        let run_id = RunId::from("run-001");

        let create = engine
            .handle_action(
                None,
                RunAction::CreateRun {
                    run_id: run_id.clone(),
                    workspace: "/tmp/demo".to_owned(),
                    task: "Test engine".to_owned(),
                    controller: AgentKind::Codex,
                },
            )
            .expect("create run");
        assert_eq!(create.len(), 1);

        let mut aggregate = RunAggregate::default();
        for (idx, event) in create.into_iter().enumerate() {
            aggregate
                .apply(&StoredRunEvent {
                    sequence: (idx + 1) as u64,
                    run_id: run_id.clone(),
                    emitted_at: clock.now(),
                    event,
                })
                .expect("apply create");
        }

        let plan_events = engine
            .handle_action(
                Some(&aggregate),
                RunAction::GeneratePlan {
                    run_id: run_id.clone(),
                },
            )
            .expect("generate plan");
        for event in plan_events {
            aggregate
                .apply(&StoredRunEvent {
                    sequence: aggregate.last_sequence() + 1,
                    run_id: run_id.clone(),
                    emitted_at: clock.now(),
                    event,
                })
                .expect("apply plan");
        }

        let start_events = engine
            .handle_action(
                Some(&aggregate),
                RunAction::StartStep {
                    run_id: run_id.clone(),
                    step_id: StepId::from("step-001"),
                    agent: AgentKind::Codex,
                },
            )
            .expect("start step");
        for event in start_events {
            aggregate
                .apply(&StoredRunEvent {
                    sequence: aggregate.last_sequence() + 1,
                    run_id: run_id.clone(),
                    emitted_at: clock.now(),
                    event,
                })
                .expect("apply start step");
        }

        let complete_events = engine
            .handle_action(
                Some(&aggregate),
                RunAction::CompleteStep {
                    run_id: run_id.clone(),
                    step_id: StepId::from("step-001"),
                    summary: Some("done".to_owned()),
                },
            )
            .expect("complete step");
        for event in complete_events {
            aggregate
                .apply(&StoredRunEvent {
                    sequence: aggregate.last_sequence() + 1,
                    run_id: run_id.clone(),
                    emitted_at: clock.now(),
                    event,
                })
                .expect("apply complete step");
        }

        let projection = aggregate.projection().expect("projection");
        let step = projection.plan.expect("plan").steps[0].clone();
        assert_eq!(step.status, StepStatus::Completed);
    }

    #[test]
    fn engine_can_fail_and_retry_a_step() {
        let clock = SequencedClock::new(Utc.with_ymd_and_hms(2026, 4, 2, 0, 0, 0).unwrap());
        let engine = RunEngine::new(clock.clone());
        let run_id = RunId::from("run-002");

        let mut aggregate = RunAggregate::default();
        for action in [
            RunAction::CreateRun {
                run_id: run_id.clone(),
                workspace: "/tmp/demo".to_owned(),
                task: "Retry engine".to_owned(),
                controller: AgentKind::Codex,
            },
            RunAction::GeneratePlan {
                run_id: run_id.clone(),
            },
            RunAction::StartStep {
                run_id: run_id.clone(),
                step_id: StepId::from("step-001"),
                agent: AgentKind::Codex,
            },
            RunAction::FailStep {
                run_id: run_id.clone(),
                step_id: StepId::from("step-001"),
                kind: StepFailureKind::Interrupted,
                reason: "stopped".to_owned(),
            },
            RunAction::RetryStep {
                run_id: run_id.clone(),
                step_id: StepId::from("step-001"),
            },
        ] {
            for event in engine
                .handle_action(Some(&aggregate).filter(|_| aggregate.metadata().is_some()), action)
                .or_else(|_| engine.handle_action(None, RunAction::CreateRun {
                    run_id: run_id.clone(),
                    workspace: "/tmp/demo".to_owned(),
                    task: "Retry engine".to_owned(),
                    controller: AgentKind::Codex,
                }))
                .expect("handle action")
            {
                aggregate
                    .apply(&StoredRunEvent {
                        sequence: aggregate.last_sequence() + 1,
                        run_id: run_id.clone(),
                        emitted_at: clock.now(),
                        event,
                    })
                    .expect("apply event");
            }
        }

        let projection = aggregate.projection().expect("projection");
        let step = projection.plan.expect("plan").steps[0].clone();
        assert_eq!(projection.run.phase, RunPhase::Ready);
        assert_eq!(step.status, StepStatus::Pending);
    }
}
