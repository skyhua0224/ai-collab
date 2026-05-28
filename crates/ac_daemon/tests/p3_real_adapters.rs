use ac_daemon::{
    build_smoke_request, spawn_http_server, ApprovalResponseRequest, CreateRunRequest,
    ExecuteRunOptions, InterruptRunRequest, RunService,
};
use ac_protocol::{AgentKind, ApprovalDecision, RunPhase, StepFailureKind, StepStatus};
use reqwest::Client;
use tempfile::tempdir;
use tokio::time::{sleep, Duration};

async fn wait_for_phase(
    client: &Client,
    base: &str,
    run_id: &str,
    expected: RunPhase,
) -> ac_protocol::RunProjection {
    for _ in 0..120 {
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
        sleep(Duration::from_millis(250)).await;
    }
    panic!("phase {expected:?} was not reached");
}

#[tokio::test]
#[ignore = "requires local Codex, Claude Code, and Gemini credentials"]
async fn real_cli_adapters_can_return_summary() {
    let workspace = std::env::current_dir().expect("cwd");
    for agent in [AgentKind::Codex, AgentKind::ClaudeCode, AgentKind::GeminiCli] {
        let request = build_smoke_request(agent.clone(), workspace.clone());
        let adapter = match agent {
            AgentKind::Codex => ac_daemon::CliAgentAdapter::codex(),
            AgentKind::ClaudeCode => ac_daemon::CliAgentAdapter::claude(),
            AgentKind::GeminiCli => ac_daemon::CliAgentAdapter::gemini(),
            AgentKind::Mock => unreachable!(),
        };
        let outcome = adapter.execute(request).await.expect("adapter outcome");
        match outcome {
            ac_daemon::AdapterOutcome::Completed { summary, .. } => {
                assert!(!summary.trim().is_empty());
            }
            _ => panic!("real adapter did not complete"),
        }
    }
}

#[tokio::test]
#[ignore = "requires local Codex and Claude Code credentials"]
async fn real_multi_agent_run_supports_approval_timeout_interrupt_and_resume() {
    let temp = tempdir().expect("tempdir");
    let service = RunService::new(temp.path().join("runs")).await.expect("service");
    let handle = spawn_http_server(service, "127.0.0.1:0").await.expect("spawn");
    let base = format!("http://{}", handle.local_addr);
    let client = Client::new();

    client
        .post(format!("{base}/v1/runs"))
        .json(&CreateRunRequest {
            run_id: "run-p3-real".to_owned(),
            workspace: temp.path().display().to_string(),
            task: "Inspect the workspace briefly, then return a compact smoke summary.".to_owned(),
            controller: AgentKind::Codex,
        })
        .send()
        .await
        .expect("create")
        .error_for_status()
        .expect("status");
    client
        .post(format!("{base}/v1/runs/run-p3-real/plan"))
        .send()
        .await
        .expect("plan")
        .error_for_status()
        .expect("status");
    client
        .post(format!("{base}/v1/runs/run-p3-real/execute"))
        .json(&ExecuteRunOptions {
            mock_scenario: None,
            timeout_ms: Some(1),
        })
        .send()
        .await
        .expect("execute")
        .error_for_status()
        .expect("status");
    let timed_out = wait_for_phase(&client, &base, "run-p3-real", RunPhase::Failed).await;
    let timed_out_step = timed_out
        .plan
        .as_ref()
        .expect("plan")
        .steps
        .iter()
        .find(|step| step.status == StepStatus::Failed)
        .expect("failed step");
    assert_eq!(timed_out_step.failure_kind, Some(StepFailureKind::Timeout));

    client
        .post(format!("{base}/v1/runs/run-p3-real/resume"))
        .json(&ExecuteRunOptions {
            mock_scenario: None,
            timeout_ms: Some(30_000),
        })
        .send()
        .await
        .expect("resume after timeout")
        .error_for_status()
        .expect("status");
    let waiting = wait_for_phase(&client, &base, "run-p3-real", RunPhase::WaitingApproval).await;
    let approval_id = waiting.approvals[0].id.as_str().to_owned();
    client
        .post(format!("{base}/v1/runs/run-p3-real/approvals/{approval_id}"))
        .json(&ApprovalResponseRequest {
            decision: ApprovalDecision::Approve,
            note: Some("go".to_owned()),
        })
        .send()
        .await
        .expect("approve")
        .error_for_status()
        .expect("status");
    client
        .post(format!("{base}/v1/runs/run-p3-real/resume"))
        .json(&ExecuteRunOptions {
            mock_scenario: None,
            timeout_ms: Some(30_000),
        })
        .send()
        .await
        .expect("resume")
        .error_for_status()
        .expect("status");
    sleep(Duration::from_millis(200)).await;
    client
        .post(format!("{base}/v1/runs/run-p3-real/interrupt"))
        .json(&InterruptRunRequest)
        .send()
        .await
        .expect("interrupt")
        .error_for_status()
        .expect("status");
    let interrupted = wait_for_phase(&client, &base, "run-p3-real", RunPhase::Failed).await;
    let interrupted_step = interrupted
        .plan
        .as_ref()
        .expect("plan")
        .steps
        .iter()
        .find(|step| step.status == StepStatus::Failed)
        .expect("interrupted step");
    assert_eq!(interrupted_step.failure_kind, Some(StepFailureKind::Interrupted));

    client
        .post(format!("{base}/v1/runs/run-p3-real/resume"))
        .json(&ExecuteRunOptions {
            mock_scenario: None,
            timeout_ms: Some(30_000),
        })
        .send()
        .await
        .expect("resume after interrupt")
        .error_for_status()
        .expect("status");
    let completed = wait_for_phase(&client, &base, "run-p3-real", RunPhase::Completed).await;
    assert!(completed
        .plan
        .as_ref()
        .expect("plan")
        .steps
        .iter()
        .all(|step| step.status == StepStatus::Completed));

    handle.shutdown().await;
}
