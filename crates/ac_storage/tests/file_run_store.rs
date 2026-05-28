use ac_core::RunAggregate;
use ac_engine::{Clock, RunEngine, SequencedClock};
use ac_protocol::{AgentKind, RunAction, RunId, StepId};
use ac_storage::FileRunStore;
use chrono::{TimeZone, Utc};
use tempfile::tempdir;

#[test]
fn file_run_store_can_save_and_recover_projection() {
    let temp = tempdir().expect("tempdir");
    let store = FileRunStore::new(temp.path().join("runs"));
    let clock = SequencedClock::new(Utc.with_ymd_and_hms(2026, 4, 2, 8, 0, 0).unwrap());
    let engine = RunEngine::new(clock.clone());
    let run_id = RunId::from("run-storage-001");

    let actions = vec![
        RunAction::CreateRun {
            run_id: run_id.clone(),
            workspace: "/tmp/project".to_owned(),
            task: "Verify file-backed recovery".to_owned(),
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
        RunAction::CompleteStep {
            run_id: run_id.clone(),
            step_id: StepId::from("step-001"),
            summary: Some("Collected the first evidence pack.".to_owned()),
        },
    ];

    let mut aggregate: Option<RunAggregate> = None;
    for action in actions {
        let emitted = engine
            .handle_action(aggregate.as_ref(), action)
            .expect("engine action");
        let stored = store
            .append_events(&run_id, &emitted, clock.now())
            .expect("append events");
        let mut next = aggregate.clone().unwrap_or_default();
        for event in &stored {
            next.apply(event).expect("apply stored event");
        }
        aggregate = Some(next);
    }

    let projection = aggregate
        .as_ref()
        .expect("aggregate")
        .projection()
        .expect("projection");
    store
        .save_snapshot(&run_id, &projection)
        .expect("save snapshot");

    let loaded_snapshot = store
        .load_snapshot(&run_id)
        .expect("load snapshot")
        .expect("snapshot exists");
    assert_eq!(loaded_snapshot, projection);

    let rebuilt = store
        .rebuild_projection(&run_id)
        .expect("rebuild projection");
    assert_eq!(rebuilt, projection);
}
