use ac_protocol::{
    ApprovalDecision, ApprovalId, ApprovalRequest, ApprovalStatus, Artifact, Plan, PlanStep,
    RunEvent, RunMetadata, RunPhase, RunProjection, StepFailureKind, StepId, StepStatus,
    StoredRunEvent,
};
use std::collections::BTreeMap;
use thiserror::Error;

#[derive(Debug, Error, PartialEq, Eq)]
pub enum AggregateError {
    #[error("run metadata does not exist")]
    MissingRun,
    #[error("run metadata already exists")]
    RunAlreadyExists,
    #[error("plan does not exist")]
    MissingPlan,
    #[error("plan already exists")]
    PlanAlreadyExists,
    #[error("step {0} does not exist")]
    MissingStep(StepId),
    #[error("step {step_id} expected status {expected:?}, found {actual:?}")]
    InvalidStepStatus {
        step_id: StepId,
        expected: StepStatus,
        actual: StepStatus,
    },
    #[error("approval {0} does not exist")]
    MissingApproval(ApprovalId),
    #[error("approval {approval_id} is not pending")]
    ApprovalNotPending { approval_id: ApprovalId },
}

#[derive(Debug, Clone, Default)]
pub struct RunAggregate {
    metadata: Option<RunMetadata>,
    plan: Option<Plan>,
    approvals: BTreeMap<ApprovalId, ApprovalRequest>,
    artifacts: Vec<Artifact>,
    event_count: usize,
    last_sequence: u64,
}

impl RunAggregate {
    pub fn metadata(&self) -> Option<&RunMetadata> {
        self.metadata.as_ref()
    }

    pub fn plan(&self) -> Option<&Plan> {
        self.plan.as_ref()
    }

    pub fn approval_count(&self) -> usize {
        self.approvals.len()
    }

    pub fn artifact_count(&self) -> usize {
        self.artifacts.len()
    }

    pub fn last_sequence(&self) -> u64 {
        self.last_sequence
    }

    pub fn event_count(&self) -> usize {
        self.event_count
    }

    pub fn projection(&self) -> Result<RunProjection, AggregateError> {
        let run = self.metadata.clone().ok_or(AggregateError::MissingRun)?;
        let approvals = self.approvals.values().cloned().collect::<Vec<_>>();
        Ok(RunProjection {
            run,
            plan: self.plan.clone(),
            approvals,
            artifacts: self.artifacts.clone(),
            event_count: self.event_count,
            last_sequence: self.last_sequence,
        })
    }

    pub fn replay(events: &[StoredRunEvent]) -> Result<Self, AggregateError> {
        let mut aggregate = Self::default();
        for event in events {
            aggregate.apply(event)?;
        }
        Ok(aggregate)
    }

    pub fn apply(&mut self, stored: &StoredRunEvent) -> Result<(), AggregateError> {
        match &stored.event {
            RunEvent::RunCreated { metadata } => {
                if self.metadata.is_some() {
                    return Err(AggregateError::RunAlreadyExists);
                }
                self.metadata = Some(metadata.clone());
            }
            RunEvent::PlanGenerated { plan } => {
                let metadata = self.metadata.as_mut().ok_or(AggregateError::MissingRun)?;
                if self.plan.is_some() {
                    return Err(AggregateError::PlanAlreadyExists);
                }
                metadata.phase = RunPhase::Ready;
                metadata.updated_at = stored.emitted_at;
                self.plan = Some(plan.clone());
            }
            RunEvent::StepStarted {
                step_id,
                agent,
                started_at,
            } => {
                if self.metadata.is_none() {
                    return Err(AggregateError::MissingRun);
                }
                let step = self.step_mut(step_id)?;
                if step.status != StepStatus::Pending {
                    return Err(AggregateError::InvalidStepStatus {
                        step_id: step_id.clone(),
                        expected: StepStatus::Pending,
                        actual: step.status.clone(),
                    });
                }
                step.status = StepStatus::Running;
                step.assignee = Some(agent.clone());
                step.started_at = Some(*started_at);
                step.completed_at = None;
                step.summary = None;
                step.failure_kind = None;
                step.failure_reason = None;
                let metadata = self.metadata.as_mut().ok_or(AggregateError::MissingRun)?;
                metadata.phase = RunPhase::Running;
                metadata.updated_at = stored.emitted_at;
            }
            RunEvent::StepCompleted {
                step_id,
                completed_at,
                summary,
            } => {
                if self.metadata.is_none() {
                    return Err(AggregateError::MissingRun);
                }
                let step = self.step_mut(step_id)?;
                if step.status != StepStatus::Running {
                    return Err(AggregateError::InvalidStepStatus {
                        step_id: step_id.clone(),
                        expected: StepStatus::Running,
                        actual: step.status.clone(),
                    });
                }
                step.status = StepStatus::Completed;
                step.completed_at = Some(*completed_at);
                step.summary = summary.clone();
                step.failure_kind = None;
                step.failure_reason = None;
                let next_phase = self.derive_phase();
                let metadata = self.metadata.as_mut().ok_or(AggregateError::MissingRun)?;
                metadata.updated_at = stored.emitted_at;
                metadata.phase = next_phase;
            }
            RunEvent::StepFailed {
                step_id,
                failed_at,
                kind,
                reason,
            } => {
                if self.metadata.is_none() {
                    return Err(AggregateError::MissingRun);
                }
                let step = self.step_mut(step_id)?;
                if step.status != StepStatus::Running {
                    return Err(AggregateError::InvalidStepStatus {
                        step_id: step_id.clone(),
                        expected: StepStatus::Running,
                        actual: step.status.clone(),
                    });
                }
                step.status = StepStatus::Failed;
                step.completed_at = Some(*failed_at);
                step.summary = None;
                step.failure_kind = Some(kind.clone());
                step.failure_reason = Some(reason.clone());
                let metadata = self.metadata.as_mut().ok_or(AggregateError::MissingRun)?;
                metadata.updated_at = stored.emitted_at;
                metadata.phase = RunPhase::Failed;
            }
            RunEvent::StepRetried {
                step_id,
                retried_at: _,
            } => {
                if self.metadata.is_none() {
                    return Err(AggregateError::MissingRun);
                }
                let step = self.step_mut(step_id)?;
                if step.status != StepStatus::Failed && step.status != StepStatus::Blocked {
                    return Err(AggregateError::InvalidStepStatus {
                        step_id: step_id.clone(),
                        expected: StepStatus::Failed,
                        actual: step.status.clone(),
                    });
                }
                step.status = StepStatus::Pending;
                step.assignee = None;
                step.started_at = None;
                step.completed_at = None;
                step.summary = None;
                step.failure_kind = None;
                step.failure_reason = None;
                let next_phase = self.derive_phase();
                let metadata = self.metadata.as_mut().ok_or(AggregateError::MissingRun)?;
                metadata.updated_at = stored.emitted_at;
                metadata.phase = next_phase;
            }
            RunEvent::ApprovalRequested { approval } => {
                let metadata = self.metadata.as_mut().ok_or(AggregateError::MissingRun)?;
                self.approvals.insert(approval.id.clone(), approval.clone());
                metadata.updated_at = stored.emitted_at;
                metadata.phase = RunPhase::WaitingApproval;
            }
            RunEvent::ApprovalResponded {
                approval_id,
                decision,
                responded_at,
                note,
            } => {
                if self.metadata.is_none() {
                    return Err(AggregateError::MissingRun);
                }
                let approval = self
                    .approvals
                    .get_mut(approval_id)
                    .ok_or_else(|| AggregateError::MissingApproval(approval_id.clone()))?;
                if approval.status != ApprovalStatus::Pending {
                    return Err(AggregateError::ApprovalNotPending {
                        approval_id: approval_id.clone(),
                    });
                }
                approval.status = match decision {
                    ApprovalDecision::Approve => ApprovalStatus::Approved,
                    ApprovalDecision::Deny => ApprovalStatus::Denied,
                };
                approval.responded_at = Some(*responded_at);
                approval.response_note = note.clone();
                let next_phase = self.derive_phase();
                let metadata = self.metadata.as_mut().ok_or(AggregateError::MissingRun)?;
                metadata.updated_at = stored.emitted_at;
                metadata.phase = next_phase;
            }
            RunEvent::ArtifactRegistered { artifact } => {
                let metadata = self.metadata.as_mut().ok_or(AggregateError::MissingRun)?;
                self.artifacts.push(artifact.clone());
                metadata.updated_at = stored.emitted_at;
            }
        }

        self.event_count += 1;
        self.last_sequence = stored.sequence;
        Ok(())
    }

    fn step_mut(&mut self, step_id: &StepId) -> Result<&mut PlanStep, AggregateError> {
        let plan = self.plan.as_mut().ok_or(AggregateError::MissingPlan)?;
        plan.steps
            .iter_mut()
            .find(|step| &step.id == step_id)
            .ok_or_else(|| AggregateError::MissingStep(step_id.clone()))
    }

    fn derive_phase(&self) -> RunPhase {
        if self
            .approvals
            .values()
            .any(|approval| approval.status == ApprovalStatus::Pending)
        {
            return RunPhase::WaitingApproval;
        }

        if self
            .approvals
            .values()
            .any(|approval| approval.status == ApprovalStatus::Denied)
        {
            return RunPhase::Failed;
        }

        if let Some(plan) = &self.plan {
            if plan.steps.iter().any(|step| step.status == StepStatus::Failed) {
                return RunPhase::Failed;
            }

            if plan
                .steps
                .iter()
                .all(|step| step.status == StepStatus::Completed)
            {
                return RunPhase::Completed;
            }

            if plan
                .steps
                .iter()
                .any(|step| step.status == StepStatus::Running)
            {
                return RunPhase::Running;
            }
        }

        RunPhase::Ready
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use ac_protocol::{AgentKind, PlanId, ResponsibilityStage, RunId};
    use chrono::{TimeZone, Utc};

    fn stored(event: RunEvent, seq: u64) -> StoredRunEvent {
        StoredRunEvent {
            sequence: seq,
            run_id: RunId::from("run-001"),
            emitted_at: Utc.with_ymd_and_hms(2026, 4, 2, 0, 0, seq as u32).unwrap(),
            event,
        }
    }

    #[test]
    fn aggregate_replays_events_into_projection() {
        let metadata = RunMetadata {
            id: RunId::from("run-001"),
            workspace: "/tmp/demo".to_owned(),
            task: "Test P1".to_owned(),
            controller: AgentKind::Codex,
            phase: RunPhase::Created,
            created_at: Utc.with_ymd_and_hms(2026, 4, 2, 0, 0, 0).unwrap(),
            updated_at: Utc.with_ymd_and_hms(2026, 4, 2, 0, 0, 0).unwrap(),
        };
        let plan = Plan {
            id: PlanId::from("plan-001"),
            version: 1,
            generated_at: Utc.with_ymd_and_hms(2026, 4, 2, 0, 0, 1).unwrap(),
            steps: vec![PlanStep {
                id: StepId::from("step-001"),
                title: "Collect context".to_owned(),
                stage: ResponsibilityStage::Collect,
                status: StepStatus::Pending,
                assignee: None,
                done_when: "Done".to_owned(),
                eta_minutes: Some(15),
                started_at: None,
                completed_at: None,
                summary: None,
                failure_kind: None,
                failure_reason: None,
            }],
        };

        let events = vec![
            stored(RunEvent::RunCreated { metadata }, 1),
            stored(RunEvent::PlanGenerated { plan }, 2),
        ];

        let aggregate = RunAggregate::replay(&events).expect("replay events");
        let projection = aggregate.projection().expect("projection");

        assert_eq!(projection.run.phase, RunPhase::Ready);
        assert_eq!(projection.plan.expect("plan").steps.len(), 1);
        assert_eq!(projection.event_count, 2);
    }

    #[test]
    fn aggregate_handles_step_failure_and_retry() {
        let metadata = RunMetadata {
            id: RunId::from("run-001"),
            workspace: "/tmp/demo".to_owned(),
            task: "Test failure".to_owned(),
            controller: AgentKind::Codex,
            phase: RunPhase::Created,
            created_at: Utc.with_ymd_and_hms(2026, 4, 2, 0, 0, 0).unwrap(),
            updated_at: Utc.with_ymd_and_hms(2026, 4, 2, 0, 0, 0).unwrap(),
        };
        let plan = Plan {
            id: PlanId::from("plan-001"),
            version: 1,
            generated_at: Utc.with_ymd_and_hms(2026, 4, 2, 0, 0, 1).unwrap(),
            steps: vec![PlanStep {
                id: StepId::from("step-001"),
                title: "Execute".to_owned(),
                stage: ResponsibilityStage::Execute,
                status: StepStatus::Pending,
                assignee: None,
                done_when: "Done".to_owned(),
                eta_minutes: Some(15),
                started_at: None,
                completed_at: None,
                summary: None,
                failure_kind: None,
                failure_reason: None,
            }],
        };

        let events = vec![
            stored(RunEvent::RunCreated { metadata }, 1),
            stored(RunEvent::PlanGenerated { plan }, 2),
            stored(
                RunEvent::StepStarted {
                    step_id: StepId::from("step-001"),
                    agent: AgentKind::Codex,
                    started_at: Utc.with_ymd_and_hms(2026, 4, 2, 0, 0, 2).unwrap(),
                },
                3,
            ),
            stored(
                RunEvent::StepFailed {
                    step_id: StepId::from("step-001"),
                    failed_at: Utc.with_ymd_and_hms(2026, 4, 2, 0, 0, 3).unwrap(),
                    kind: StepFailureKind::Timeout,
                    reason: "timed out".to_owned(),
                },
                4,
            ),
            stored(
                RunEvent::StepRetried {
                    step_id: StepId::from("step-001"),
                    retried_at: Utc.with_ymd_and_hms(2026, 4, 2, 0, 0, 4).unwrap(),
                },
                5,
            ),
        ];

        let aggregate = RunAggregate::replay(&events).expect("replay events");
        let projection = aggregate.projection().expect("projection");
        let step = projection.plan.expect("plan").steps[0].clone();

        assert_eq!(projection.run.phase, RunPhase::Ready);
        assert_eq!(step.status, StepStatus::Pending);
        assert_eq!(step.failure_kind, None);
        assert_eq!(step.failure_reason, None);
    }
}
