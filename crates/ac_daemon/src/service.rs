use crate::adapter::{
    AdapterError, AdapterRegistry, AdapterOutcome, AgentExecutionRequest, MockScenario,
};
use ac_core::RunAggregate;
use ac_engine::RunEngine;
use ac_protocol::{
    AgentKind, ApprovalDecision, ApprovalStatus, ArtifactKind, PlanStep, ResponsibilityStage,
    RunAction, RunId, RunPhase, RunProjection, StepFailureKind, StepId, StepStatus, StoredRunEvent,
};
use ac_storage::{FileRunStore, StorageError};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Arc;
use thiserror::Error;
use tokio::sync::{broadcast, Mutex, RwLock};
use tokio::task::JoinHandle;
use tokio::time::Duration;
use tokio_util::sync::CancellationToken;

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ExecuteRunOptions {
    pub mock_scenario: Option<MockScenario>,
    pub timeout_ms: Option<u64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum StreamEnvelope {
    Snapshot { projection: RunProjection },
    Update { event: StoredRunEvent, projection: RunProjection },
}

#[derive(Debug, Error)]
pub enum ServiceError {
    #[error("storage error: {0}")]
    Storage(#[from] StorageError),
    #[error("engine error: {0}")]
    Engine(#[from] ac_engine::EngineError),
    #[error("run {0} was not found")]
    RunNotFound(RunId),
    #[error("run {0} has no plan")]
    MissingPlan(RunId),
    #[error("adapter {0:?} is unavailable")]
    AdapterUnavailable(AgentKind),
}

struct RunningExecution {
    cancel: CancellationToken,
    handle: JoinHandle<()>,
}

struct RunServiceInner {
    store: FileRunStore,
    engine: RunEngine,
    adapters: AdapterRegistry,
    projections: RwLock<HashMap<RunId, RunProjection>>,
    running: Mutex<HashMap<RunId, RunningExecution>>,
    broadcaster: broadcast::Sender<StreamEnvelope>,
}

#[derive(Clone)]
pub struct RunService {
    inner: Arc<RunServiceInner>,
}

impl RunService {
    pub async fn new(base_dir: impl Into<PathBuf>) -> Result<Self, ServiceError> {
        let store = FileRunStore::new(base_dir.into());
        std::fs::create_dir_all(store.base_dir())?;
        let (broadcaster, _) = broadcast::channel(256);
        let service = Self {
            inner: Arc::new(RunServiceInner {
                store,
                engine: RunEngine::default(),
                adapters: AdapterRegistry::new(),
                projections: RwLock::new(HashMap::new()),
                running: Mutex::new(HashMap::new()),
                broadcaster,
            }),
        };
        service.reload_from_disk().await?;
        Ok(service)
    }

    pub fn subscribe(&self) -> broadcast::Receiver<StreamEnvelope> {
        self.inner.broadcaster.subscribe()
    }

    pub async fn list_runs(&self) -> Vec<RunProjection> {
        let mut projections = self
            .inner
            .projections
            .read()
            .await
            .values()
            .cloned()
            .collect::<Vec<_>>();
        projections.sort_by(|left, right| left.run.id.as_str().cmp(right.run.id.as_str()));
        projections
    }

    pub async fn get_run(&self, run_id: &RunId) -> Option<RunProjection> {
        self.inner.projections.read().await.get(run_id).cloned()
    }

    pub fn available_adapters(&self) -> Vec<AgentKind> {
        self.inner.adapters.available()
    }

    pub async fn create_run(
        &self,
        run_id: RunId,
        workspace: String,
        task: String,
        controller: AgentKind,
    ) -> Result<RunProjection, ServiceError> {
        self.apply_action(RunAction::CreateRun {
            run_id,
            workspace,
            task,
            controller,
        })
        .await
    }

    pub async fn generate_plan(&self, run_id: RunId) -> Result<RunProjection, ServiceError> {
        self.apply_action(RunAction::GeneratePlan { run_id }).await
    }

    pub async fn submit_action(&self, action: RunAction) -> Result<RunProjection, ServiceError> {
        self.apply_action(action).await
    }

    pub async fn respond_approval(
        &self,
        run_id: RunId,
        approval_id: ac_protocol::ApprovalId,
        decision: ApprovalDecision,
        note: Option<String>,
    ) -> Result<RunProjection, ServiceError> {
        self.apply_action(RunAction::RespondApproval {
            run_id,
            approval_id,
            decision,
            note,
        })
        .await
    }

    pub async fn start_execution(
        &self,
        run_id: RunId,
        options: ExecuteRunOptions,
    ) -> Result<RunProjection, ServiceError> {
        if self.inner.running.lock().await.contains_key(&run_id) {
            return self
                .get_run(&run_id)
                .await
                .ok_or_else(|| ServiceError::RunNotFound(run_id));
        }

        let cancel = CancellationToken::new();
        let service = self.clone();
        let run_id_for_task = run_id.clone();
        let cancel_for_task = cancel.clone();
        let options_for_task = options.clone();
        let handle = tokio::spawn(async move {
            service
                .run_loop(run_id_for_task.clone(), options_for_task, cancel_for_task)
                .await;
            service.inner.running.lock().await.remove(&run_id_for_task);
        });
        self.inner
            .running
            .lock()
            .await
            .insert(run_id.clone(), RunningExecution { cancel, handle });

        self.get_run(&run_id)
            .await
            .ok_or_else(|| ServiceError::RunNotFound(run_id))
    }

    pub async fn resume_execution(
        &self,
        run_id: RunId,
        options: ExecuteRunOptions,
    ) -> Result<RunProjection, ServiceError> {
        if let Some(step_id) = self.first_failed_step(&run_id).await? {
            self.apply_action(RunAction::RetryStep {
                run_id: run_id.clone(),
                step_id,
            })
            .await?;
        }
        self.start_execution(run_id.clone(), options).await?;
        self.get_run(&run_id)
            .await
            .ok_or_else(|| ServiceError::RunNotFound(run_id))
    }

    pub async fn interrupt_execution(&self, run_id: RunId) -> Result<RunProjection, ServiceError> {
        let maybe_running = self.inner.running.lock().await.remove(&run_id);
        if let Some(running) = maybe_running {
            running.cancel.cancel();
            let _ = running.handle.await;
        }
        self.get_run(&run_id)
            .await
            .ok_or_else(|| ServiceError::RunNotFound(run_id))
    }

    async fn reload_from_disk(&self) -> Result<(), ServiceError> {
        let run_ids = self.inner.store.list_run_ids()?;
        let mut projections = HashMap::new();
        for run_id in run_ids {
            if let Ok(projection) = self.inner.store.rebuild_projection(&run_id) {
                projections.insert(run_id, projection);
            }
        }
        *self.inner.projections.write().await = projections;
        Ok(())
    }

    async fn apply_action(&self, action: RunAction) -> Result<RunProjection, ServiceError> {
        let run_id = action.run_id().clone();
        let current = self.load_aggregate(&run_id)?;
        let emitted = self.inner.engine.handle_action(current.as_ref(), action)?;
        let stored = self
            .inner
            .store
            .append_events(&run_id, &emitted, chrono::Utc::now())?;
        let projection = self.inner.store.rebuild_projection(&run_id)?;
        self.inner.store.save_snapshot(&run_id, &projection)?;
        self.inner
            .projections
            .write()
            .await
            .insert(run_id.clone(), projection.clone());
        for event in stored {
            let _ = self.inner.broadcaster.send(StreamEnvelope::Update {
                event,
                projection: projection.clone(),
            });
        }
        Ok(projection)
    }

    fn load_aggregate(&self, run_id: &RunId) -> Result<Option<RunAggregate>, ServiceError> {
        let events = self.inner.store.load_events(run_id)?;
        if events.is_empty() {
            Ok(None)
        } else {
            Ok(Some(RunAggregate::replay(&events)?))
        }
    }

    async fn run_loop(&self, run_id: RunId, options: ExecuteRunOptions, cancel: CancellationToken) {
        loop {
            if cancel.is_cancelled() {
                break;
            }

            let projection = match self.get_run(&run_id).await {
                Some(projection) => projection,
                None => break,
            };

            match projection.run.phase {
                RunPhase::Completed | RunPhase::Failed | RunPhase::WaitingApproval => break,
                _ => {}
            }

            let Some(plan) = projection.plan.clone() else {
                break;
            };

            let Some(step) = plan.steps.into_iter().find(|step| step.status == StepStatus::Pending) else {
                break;
            };

            if self.step_requires_approval(&projection, &step) {
                let _ = self
                    .apply_action(RunAction::RequestApproval {
                        run_id: run_id.clone(),
                        step_id: Some(step.id.clone()),
                        title: format!("Approve {}", step.title),
                        reason: format!("{} is about to enter {:?}", step.id, step.stage),
                        scope: "step-execution".to_owned(),
                    })
                    .await;
                break;
            }

            let agent = match self.select_agent(&projection, &step) {
                Ok(agent) => agent,
                Err(_) => {
                    let _ = self
                        .apply_action(RunAction::FailStep {
                            run_id: run_id.clone(),
                            step_id: step.id.clone(),
                            kind: StepFailureKind::AdapterError,
                            reason: "no adapter available".to_owned(),
                        })
                        .await;
                    break;
                }
            };

            if self
                .apply_action(RunAction::StartStep {
                    run_id: run_id.clone(),
                    step_id: step.id.clone(),
                    agent: agent.clone(),
                })
                .await
                .is_err()
            {
                break;
            }

            let current = match self.get_run(&run_id).await {
                Some(projection) => projection,
                None => break,
            };

            let current_step = current
                .plan
                .as_ref()
                .and_then(|plan| plan.steps.iter().find(|candidate| candidate.id == step.id))
                .cloned()
                .unwrap_or(step.clone());

            let timeout = Duration::from_millis(options.timeout_ms.unwrap_or(20_000));
            let request = AgentExecutionRequest {
                workspace: PathBuf::from(current.run.workspace.clone()),
                run_id: run_id.clone(),
                task: current.run.task.clone(),
                step: current_step.clone(),
                projection: current.clone(),
                mock_scenario: options.mock_scenario.clone(),
                cancel: cancel.clone(),
            };

            let Some(adapter) = self.inner.adapters.get(&agent) else {
                let _ = self
                    .apply_action(RunAction::FailStep {
                        run_id: run_id.clone(),
                        step_id: current_step.id.clone(),
                        kind: StepFailureKind::AdapterError,
                        reason: format!("adapter {:?} was not found", agent),
                    })
                    .await;
                break;
            };

            let outcome = tokio::time::timeout(timeout, adapter.execute(request)).await;
            match outcome {
                Err(_) => {
                    let _ = self
                        .apply_action(RunAction::FailStep {
                            run_id: run_id.clone(),
                            step_id: current_step.id.clone(),
                            kind: StepFailureKind::Timeout,
                            reason: format!("step {} timed out", current_step.id),
                        })
                        .await;
                    break;
                }
                Ok(Err(AdapterError::Interrupted)) => {
                    let _ = self
                        .apply_action(RunAction::FailStep {
                            run_id: run_id.clone(),
                            step_id: current_step.id.clone(),
                            kind: StepFailureKind::Interrupted,
                            reason: format!("step {} was interrupted", current_step.id),
                        })
                        .await;
                    break;
                }
                Ok(Err(error)) => {
                    let _ = self
                        .apply_action(RunAction::FailStep {
                            run_id: run_id.clone(),
                            step_id: current_step.id.clone(),
                            kind: StepFailureKind::AdapterError,
                            reason: error.to_string(),
                        })
                        .await;
                    break;
                }
                Ok(Ok(AdapterOutcome::Failed { kind, reason })) => {
                    let _ = self
                        .apply_action(RunAction::FailStep {
                            run_id: run_id.clone(),
                            step_id: current_step.id.clone(),
                            kind,
                            reason,
                        })
                        .await;
                    break;
                }
                Ok(Ok(AdapterOutcome::Completed { summary, artifact })) => {
                    if let Some(artifact) = artifact {
                        let _ = self
                            .apply_action(RunAction::RegisterArtifact {
                                run_id: run_id.clone(),
                                kind: artifact.kind,
                                label: artifact.label,
                                path: artifact.path,
                                preview: artifact.preview,
                            })
                            .await;
                    } else if current_step.stage == ResponsibilityStage::Validate {
                        let _ = self
                            .apply_action(RunAction::RegisterArtifact {
                                run_id: run_id.clone(),
                                kind: ArtifactKind::Report,
                                label: format!("Validation {}", current_step.id),
                                path: None,
                                preview: Some(summary.clone()),
                            })
                            .await;
                    }
                    if self
                        .apply_action(RunAction::CompleteStep {
                            run_id: run_id.clone(),
                            step_id: current_step.id.clone(),
                            summary: Some(summary),
                        })
                        .await
                        .is_err()
                    {
                        break;
                    }
                }
            }
        }
    }

    async fn first_failed_step(&self, run_id: &RunId) -> Result<Option<StepId>, ServiceError> {
        let projection = self
            .get_run(run_id)
            .await
            .ok_or_else(|| ServiceError::RunNotFound(run_id.clone()))?;
        Ok(projection.plan.and_then(|plan| {
            plan.steps
                .into_iter()
                .find(|step| step.status == StepStatus::Failed || step.status == StepStatus::Blocked)
                .map(|step| step.id)
        }))
    }

    fn select_agent(
        &self,
        projection: &RunProjection,
        step: &PlanStep,
    ) -> Result<AgentKind, ServiceError> {
        if projection.run.controller == AgentKind::Mock {
            return Ok(AgentKind::Mock);
        }

        let preferred = match step.stage {
            ResponsibilityStage::Model | ResponsibilityStage::Plan | ResponsibilityStage::Artifact => {
                AgentKind::GeminiCli
            }
            ResponsibilityStage::Validate => AgentKind::ClaudeCode,
            ResponsibilityStage::Collect
            | ResponsibilityStage::Execute
            | ResponsibilityStage::Correct
            | ResponsibilityStage::Deliver => projection.run.controller.clone(),
        };

        if self.inner.adapters.get(&preferred).is_some() {
            Ok(preferred)
        } else if self.inner.adapters.get(&projection.run.controller).is_some() {
            Ok(projection.run.controller.clone())
        } else {
            self.inner
                .adapters
                .available()
                .into_iter()
                .next()
                .ok_or(ServiceError::AdapterUnavailable(preferred))
        }
    }

    fn step_requires_approval(&self, projection: &RunProjection, step: &PlanStep) -> bool {
        if step.stage != ResponsibilityStage::Execute {
            return false;
        }

        let approved = projection.approvals.iter().any(|approval| {
            approval.step_id.as_ref() == Some(&step.id) && approval.status == ApprovalStatus::Approved
        });
        let pending = projection.approvals.iter().any(|approval| {
            approval.step_id.as_ref() == Some(&step.id) && approval.status == ApprovalStatus::Pending
        });

        !approved && !pending
    }
}

