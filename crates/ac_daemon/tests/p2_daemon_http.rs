use ac_daemon::{
    spawn_http_server, ApprovalResponseRequest, CreateRunRequest, ExecuteRunOptions,
    InterruptRunRequest, MockScenario, RunService, StreamEnvelope,
};
use ac_protocol::{AgentKind, ApprovalDecision, RunPhase, StepFailureKind, StepStatus};
use futures_util::StreamExt;
use reqwest::Client;
use tempfile::tempdir;
use tokio::time::{sleep, Duration};
use tokio_tungstenite::connect_async;

async fn wait_for_phase(
    client: &Client,
    base: &str,
    run_id: &str,
    expected: RunPhase,
) -> ac_protocol::RunProjection {
    for _ in 0..80 {
        let projection = client
            .get(format!("{base}/v1/runs/{run_id}"))
            .send()
            .await
            .expect("get run")
            .error_for_status()
            .expect("status ok")
            .json::<ac_protocol::RunProjection>()
            .await
            .expect("projection");
        if projection.run.phase == expected {
            return projection;
        }
        sleep(Duration::from_millis(50)).await;
    }
    panic!("phase {expected:?} was not reached");
}

#[tokio::test]
async fn daemon_supports_create_plan_approval_resume_and_projection_sync() {
    let temp = tempdir().expect("tempdir");
    let service = RunService::new(temp.path().join("runs")).await.expect("service");
    let handle = spawn_http_server(service, "127.0.0.1:0").await.expect("spawn");
    let base = format!("http://{}", handle.local_addr);
    let client = Client::new();

    client
        .post(format!("{base}/v1/runs"))
        .json(&CreateRunRequest {
            run_id: "run-p2-001".to_owned(),
            workspace: temp.path().display().to_string(),
            task: "P2 smoke run".to_owned(),
            controller: AgentKind::Mock,
        })
        .send()
        .await
        .expect("create run")
        .error_for_status()
        .expect("create status");

    client
        .post(format!("{base}/v1/runs/run-p2-001/plan"))
        .send()
        .await
        .expect("generate plan")
        .error_for_status()
        .expect("plan status");

    client
        .post(format!("{base}/v1/runs/run-p2-001/execute"))
        .json(&ExecuteRunOptions::default())
        .send()
        .await
        .expect("execute")
        .error_for_status()
        .expect("execute status");

    let waiting = wait_for_phase(&client, &base, "run-p2-001", RunPhase::WaitingApproval).await;
    let approval_id = waiting.approvals[0].id.as_str().to_owned();

    let ws_url = format!("ws://{}/v1/ws?run_id=run-p2-001", handle.local_addr);
    let (mut ws_a, _) = connect_async(&ws_url).await.expect("ws a");
    let (mut ws_b, _) = connect_async(&ws_url).await.expect("ws b");

    let snapshot_a = ws_a.next().await.expect("snapshot a").expect("msg a");
    let snapshot_b = ws_b.next().await.expect("snapshot b").expect("msg b");
    let first_a = serde_json::from_str::<StreamEnvelope>(snapshot_a.to_text().expect("text a"))
        .expect("envelope a");
    let first_b = serde_json::from_str::<StreamEnvelope>(snapshot_b.to_text().expect("text b"))
        .expect("envelope b");
    match (first_a, first_b) {
        (
            StreamEnvelope::Snapshot { projection: left },
            StreamEnvelope::Snapshot { projection: right },
        ) => {
            assert_eq!(left.run.phase, RunPhase::WaitingApproval);
            assert_eq!(right.run.phase, RunPhase::WaitingApproval);
        }
        _ => panic!("expected snapshot envelopes"),
    }

    client
        .post(format!(
            "{base}/v1/runs/run-p2-001/approvals/{approval_id}"
        ))
        .json(&ApprovalResponseRequest {
            decision: ApprovalDecision::Approve,
            note: Some("continue".to_owned()),
        })
        .send()
        .await
        .expect("approve")
        .error_for_status()
        .expect("approve status");

    client
        .post(format!("{base}/v1/runs/run-p2-001/resume"))
        .json(&ExecuteRunOptions::default())
        .send()
        .await
        .expect("resume")
        .error_for_status()
        .expect("resume status");

    let completed = wait_for_phase(&client, &base, "run-p2-001", RunPhase::Completed).await;
    assert!(completed
        .plan
        .as_ref()
        .expect("plan")
        .steps
        .iter()
        .all(|step| step.status == StepStatus::Completed));

    handle.shutdown().await;
}

#[tokio::test]
async fn daemon_recovers_unfinished_run_after_restart() {
    let temp = tempdir().expect("tempdir");
    let service = RunService::new(temp.path().join("runs")).await.expect("service");
    let handle = spawn_http_server(service, "127.0.0.1:0").await.expect("spawn");
    let base = format!("http://{}", handle.local_addr);
    let client = Client::new();

    client
        .post(format!("{base}/v1/runs"))
        .json(&CreateRunRequest {
            run_id: "run-p2-restart".to_owned(),
            workspace: temp.path().display().to_string(),
            task: "Restart smoke".to_owned(),
            controller: AgentKind::Mock,
        })
        .send()
        .await
        .expect("create")
        .error_for_status()
        .expect("create status");
    client
        .post(format!("{base}/v1/runs/run-p2-restart/plan"))
        .send()
        .await
        .expect("plan")
        .error_for_status()
        .expect("plan status");
    client
        .post(format!("{base}/v1/runs/run-p2-restart/execute"))
        .json(&ExecuteRunOptions::default())
        .send()
        .await
        .expect("execute")
        .error_for_status()
        .expect("execute status");

    wait_for_phase(&client, &base, "run-p2-restart", RunPhase::WaitingApproval).await;
    handle.shutdown().await;

    let service = RunService::new(temp.path().join("runs")).await.expect("service restart");
    let handle = spawn_http_server(service, "127.0.0.1:0").await.expect("spawn restart");
    let base = format!("http://{}", handle.local_addr);
    let recovered = client
        .get(format!("{base}/v1/runs/run-p2-restart"))
        .send()
        .await
        .expect("get recovered")
        .error_for_status()
        .expect("recovered status")
        .json::<ac_protocol::RunProjection>()
        .await
        .expect("recovered projection");
    assert_eq!(recovered.run.phase, RunPhase::WaitingApproval);
    handle.shutdown().await;
}

#[tokio::test]
async fn mock_adapter_reproduces_failed_timeout_and_resume() {
    let temp = tempdir().expect("tempdir");
    let service = RunService::new(temp.path().join("runs")).await.expect("service");
    let handle = spawn_http_server(service, "127.0.0.1:0").await.expect("spawn");
    let base = format!("http://{}", handle.local_addr);
    let client = Client::new();

    client
        .post(format!("{base}/v1/runs"))
        .json(&CreateRunRequest {
            run_id: "run-p2-fail".to_owned(),
            workspace: temp.path().display().to_string(),
            task: "Mock fail".to_owned(),
            controller: AgentKind::Mock,
        })
        .send()
        .await
        .expect("create")
        .error_for_status()
        .expect("status");
    client
        .post(format!("{base}/v1/runs/run-p2-fail/plan"))
        .send()
        .await
        .expect("plan")
        .error_for_status()
        .expect("status");
    client
        .post(format!("{base}/v1/runs/run-p2-fail/execute"))
        .json(&ExecuteRunOptions::default())
        .send()
        .await
        .expect("execute")
        .error_for_status()
        .expect("status");
    let waiting = wait_for_phase(&client, &base, "run-p2-fail", RunPhase::WaitingApproval).await;
    let approval_id = waiting.approvals[0].id.as_str().to_owned();
    client
        .post(format!("{base}/v1/runs/run-p2-fail/approvals/{approval_id}"))
        .json(&ApprovalResponseRequest {
            decision: ApprovalDecision::Approve,
            note: None,
        })
        .send()
        .await
        .expect("approve")
        .error_for_status()
        .expect("status");
    client
        .post(format!("{base}/v1/runs/run-p2-fail/resume"))
        .json(&ExecuteRunOptions {
            mock_scenario: Some(MockScenario::FailOnExecute),
            timeout_ms: Some(2_000),
        })
        .send()
        .await
        .expect("resume fail")
        .error_for_status()
        .expect("status");
    let failed = wait_for_phase(&client, &base, "run-p2-fail", RunPhase::Failed).await;
    let failed_step = failed
        .plan
        .as_ref()
        .expect("plan")
        .steps
        .iter()
        .find(|step| step.status == StepStatus::Failed)
        .expect("failed step");
    assert_eq!(failed_step.failure_kind, Some(StepFailureKind::MockFailure));

    client
        .post(format!("{base}/v1/runs/run-p2-fail/resume"))
        .json(&ExecuteRunOptions::default())
        .send()
        .await
        .expect("resume success")
        .error_for_status()
        .expect("status");
    let completed = wait_for_phase(&client, &base, "run-p2-fail", RunPhase::Completed).await;
    assert!(completed
        .plan
        .as_ref()
        .expect("plan")
        .steps
        .iter()
        .all(|step| step.status == StepStatus::Completed));

    client
        .post(format!("{base}/v1/runs"))
        .json(&CreateRunRequest {
            run_id: "run-p2-timeout".to_owned(),
            workspace: temp.path().display().to_string(),
            task: "Mock timeout".to_owned(),
            controller: AgentKind::Mock,
        })
        .send()
        .await
        .expect("create timeout")
        .error_for_status()
        .expect("status");
    client
        .post(format!("{base}/v1/runs/run-p2-timeout/plan"))
        .send()
        .await
        .expect("plan timeout")
        .error_for_status()
        .expect("status");
    client
        .post(format!("{base}/v1/runs/run-p2-timeout/execute"))
        .json(&ExecuteRunOptions::default())
        .send()
        .await
        .expect("execute timeout")
        .error_for_status()
        .expect("status");
    let waiting = wait_for_phase(&client, &base, "run-p2-timeout", RunPhase::WaitingApproval).await;
    let approval_id = waiting.approvals[0].id.as_str().to_owned();
    client
        .post(format!("{base}/v1/runs/run-p2-timeout/approvals/{approval_id}"))
        .json(&ApprovalResponseRequest {
            decision: ApprovalDecision::Approve,
            note: None,
        })
        .send()
        .await
        .expect("approve timeout")
        .error_for_status()
        .expect("status");
    client
        .post(format!("{base}/v1/runs/run-p2-timeout/resume"))
        .json(&ExecuteRunOptions {
            mock_scenario: Some(MockScenario::TimeoutOnExecute),
            timeout_ms: Some(25),
        })
        .send()
        .await
        .expect("resume timeout")
        .error_for_status()
        .expect("status");
    let timed_out = wait_for_phase(&client, &base, "run-p2-timeout", RunPhase::Failed).await;
    let timed_out_step = timed_out
        .plan
        .as_ref()
        .expect("plan")
        .steps
        .iter()
        .find(|step| step.status == StepStatus::Failed)
        .expect("timed out step");
    assert_eq!(timed_out_step.failure_kind, Some(StepFailureKind::Timeout));

    handle.shutdown().await;
}

#[tokio::test]
async fn interrupt_endpoint_marks_running_step_as_interrupted() {
    let temp = tempdir().expect("tempdir");
    let service = RunService::new(temp.path().join("runs")).await.expect("service");
    let handle = spawn_http_server(service, "127.0.0.1:0").await.expect("spawn");
    let base = format!("http://{}", handle.local_addr);
    let client = Client::new();

    client
        .post(format!("{base}/v1/runs"))
        .json(&CreateRunRequest {
            run_id: "run-p2-interrupt".to_owned(),
            workspace: temp.path().display().to_string(),
            task: "Interrupt mock".to_owned(),
            controller: AgentKind::Mock,
        })
        .send()
        .await
        .expect("create")
        .error_for_status()
        .expect("status");
    client
        .post(format!("{base}/v1/runs/run-p2-interrupt/plan"))
        .send()
        .await
        .expect("plan")
        .error_for_status()
        .expect("status");
    client
        .post(format!("{base}/v1/runs/run-p2-interrupt/execute"))
        .json(&ExecuteRunOptions {
            mock_scenario: Some(MockScenario::TimeoutOnExecute),
            timeout_ms: Some(5_000),
        })
        .send()
        .await
        .expect("execute")
        .error_for_status()
        .expect("status");
    sleep(Duration::from_millis(50)).await;
    client
        .post(format!("{base}/v1/runs/run-p2-interrupt/interrupt"))
        .json(&InterruptRunRequest)
        .send()
        .await
        .expect("interrupt")
        .error_for_status()
        .expect("status");
    let interrupted = wait_for_phase(&client, &base, "run-p2-interrupt", RunPhase::Failed).await;
    let interrupted_step = interrupted
        .plan
        .as_ref()
        .expect("plan")
        .steps
        .iter()
        .find(|step| step.status == StepStatus::Failed)
        .expect("interrupted step");
    assert_eq!(interrupted_step.failure_kind, Some(StepFailureKind::Interrupted));

    handle.shutdown().await;
}

