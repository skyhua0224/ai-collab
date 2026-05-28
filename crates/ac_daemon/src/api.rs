use crate::service::{ExecuteRunOptions, RunService, ServiceError, StreamEnvelope};
use crate::toolbox::{
    FsReadRequest, FsReadResponse, SearchToolRequest, SearchToolResponse, ShellToolRequest,
    ShellToolResponse, ToolboxError,
};
use ac_protocol::{ApprovalDecision, AgentKind, RunAction, RunId};
use axum::extract::ws::{Message, WebSocket, WebSocketUpgrade};
use axum::extract::{Path, Query, State};
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::{Json, Router};
use futures_util::{SinkExt, StreamExt};
use serde::{Deserialize, Serialize};
use std::net::{SocketAddr, ToSocketAddrs};
use tokio::net::TcpListener;
use tokio::sync::oneshot;
use tokio::task::JoinHandle;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CreateRunRequest {
    pub run_id: String,
    pub workspace: String,
    pub task: String,
    pub controller: AgentKind,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ApprovalResponseRequest {
    pub decision: ApprovalDecision,
    pub note: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct InterruptRunRequest;

#[derive(Debug, Clone, Deserialize)]
struct StreamQuery {
    run_id: Option<String>,
}

pub fn build_router(service: RunService) -> Router {
    Router::new()
        .route("/health", get(health))
        .route("/v1/runs", get(list_runs).post(create_run))
        .route("/v1/runs/:run_id", get(get_run))
        .route("/v1/runs/:run_id/plan", post(generate_plan))
        .route("/v1/runs/:run_id/actions", post(submit_action))
        .route("/v1/runs/:run_id/execute", post(execute_run))
        .route("/v1/runs/:run_id/resume", post(resume_run))
        .route("/v1/runs/:run_id/interrupt", post(interrupt_run))
        .route(
            "/v1/runs/:run_id/approvals/:approval_id",
            post(respond_approval),
        )
        .route("/v1/tools/shell", post(shell_tool))
        .route("/v1/tools/fs/read", post(read_tool))
        .route("/v1/tools/search", post(search_tool))
        .route("/v1/ws", get(stream_ws))
        .with_state(service)
}

pub struct DaemonHandle {
    pub local_addr: SocketAddr,
    shutdown: Option<oneshot::Sender<()>>,
    join: JoinHandle<()>,
}

impl DaemonHandle {
    pub async fn shutdown(mut self) {
        if let Some(shutdown) = self.shutdown.take() {
            let _ = shutdown.send(());
        }
        let _ = self.join.await;
    }
}

pub async fn spawn_http_server(
    service: RunService,
    addr: impl ToSocketAddrs,
) -> Result<DaemonHandle, std::io::Error> {
    let listener = TcpListener::bind(addr.to_socket_addrs()?.next().unwrap()).await?;
    let local_addr = listener.local_addr()?;
    let app = build_router(service);
    let (shutdown_tx, shutdown_rx) = oneshot::channel();
    let join = tokio::spawn(async move {
        let _ = axum::serve(listener, app)
            .with_graceful_shutdown(async move {
                let _ = shutdown_rx.await;
            })
            .await;
    });
    Ok(DaemonHandle {
        local_addr,
        shutdown: Some(shutdown_tx),
        join,
    })
}

async fn health(State(service): State<RunService>) -> Json<serde_json::Value> {
    Json(serde_json::json!({
        "status": "ok",
        "adapters": service.available_adapters(),
        "runs": service.list_runs().await.len(),
    }))
}

async fn list_runs(State(service): State<RunService>) -> Json<Vec<ac_protocol::RunProjection>> {
    Json(service.list_runs().await)
}

async fn create_run(
    State(service): State<RunService>,
    Json(request): Json<CreateRunRequest>,
) -> Result<Json<ac_protocol::RunProjection>, ApiError> {
    Ok(Json(
        service
            .create_run(
                RunId::from(request.run_id),
                request.workspace,
                request.task,
                request.controller,
            )
            .await?,
    ))
}

async fn get_run(
    State(service): State<RunService>,
    Path(run_id): Path<String>,
) -> Result<Json<ac_protocol::RunProjection>, ApiError> {
    Ok(Json(
        service
            .get_run(&RunId::from(run_id.clone()))
            .await
            .ok_or_else(|| ServiceError::RunNotFound(RunId::from(run_id)))?,
    ))
}

async fn generate_plan(
    State(service): State<RunService>,
    Path(run_id): Path<String>,
) -> Result<Json<ac_protocol::RunProjection>, ApiError> {
    Ok(Json(service.generate_plan(RunId::from(run_id)).await?))
}

async fn submit_action(
    State(service): State<RunService>,
    Path(_run_id): Path<String>,
    Json(action): Json<RunAction>,
) -> Result<Json<ac_protocol::RunProjection>, ApiError> {
    Ok(Json(service.submit_action(action).await?))
}

async fn execute_run(
    State(service): State<RunService>,
    Path(run_id): Path<String>,
    Json(options): Json<ExecuteRunOptions>,
) -> Result<Json<ac_protocol::RunProjection>, ApiError> {
    Ok(Json(service.start_execution(RunId::from(run_id), options).await?))
}

async fn resume_run(
    State(service): State<RunService>,
    Path(run_id): Path<String>,
    Json(options): Json<ExecuteRunOptions>,
) -> Result<Json<ac_protocol::RunProjection>, ApiError> {
    Ok(Json(service.resume_execution(RunId::from(run_id), options).await?))
}

async fn interrupt_run(
    State(service): State<RunService>,
    Path(run_id): Path<String>,
    Json(_request): Json<InterruptRunRequest>,
) -> Result<Json<ac_protocol::RunProjection>, ApiError> {
    Ok(Json(service.interrupt_execution(RunId::from(run_id)).await?))
}

async fn respond_approval(
    State(service): State<RunService>,
    Path((run_id, approval_id)): Path<(String, String)>,
    Json(request): Json<ApprovalResponseRequest>,
) -> Result<Json<ac_protocol::RunProjection>, ApiError> {
    Ok(Json(
        service
            .respond_approval(
                RunId::from(run_id),
                ac_protocol::ApprovalId::from(approval_id),
                request.decision,
                request.note,
            )
            .await?,
    ))
}

async fn shell_tool(
    State(_service): State<RunService>,
    Json(request): Json<ShellToolRequest>,
) -> Result<Json<ShellToolResponse>, ApiError> {
    let toolbox = crate::LocalToolbox;
    Ok(Json(toolbox.shell(request).await?))
}

async fn read_tool(
    State(_service): State<RunService>,
    Json(request): Json<FsReadRequest>,
) -> Result<Json<FsReadResponse>, ApiError> {
    let toolbox = crate::LocalToolbox;
    Ok(Json(toolbox.read_text(request).await?))
}

async fn search_tool(
    State(_service): State<RunService>,
    Json(request): Json<SearchToolRequest>,
) -> Result<Json<SearchToolResponse>, ApiError> {
    let toolbox = crate::LocalToolbox;
    Ok(Json(toolbox.search(request).await?))
}

async fn stream_ws(
    State(service): State<RunService>,
    Query(query): Query<StreamQuery>,
    ws: WebSocketUpgrade,
) -> impl IntoResponse {
    ws.on_upgrade(move |socket| async move {
        handle_socket(socket, service, query.run_id.map(RunId::from)).await;
    })
}

async fn handle_socket(mut socket: WebSocket, service: RunService, filter: Option<RunId>) {
    for projection in service.list_runs().await {
        if filter
            .as_ref()
            .map(|run_id| run_id != &projection.run.id)
            .unwrap_or(false)
        {
            continue;
        }
        let payload = serde_json::to_string(&StreamEnvelope::Snapshot { projection });
        if let Ok(payload) = payload {
            if socket.send(Message::Text(payload)).await.is_err() {
                return;
            }
        }
    }

    let mut receiver = service.subscribe();
    loop {
        tokio::select! {
            incoming = socket.next() => {
                if incoming.is_none() {
                    break;
                }
            }
            item = receiver.recv() => {
                let Ok(item) = item else {
                    break;
                };
                let matches = match (&filter, &item) {
                    (Some(run_id), StreamEnvelope::Snapshot { projection }) => &projection.run.id == run_id,
                    (Some(run_id), StreamEnvelope::Update { projection, .. }) => &projection.run.id == run_id,
                    (None, _) => true,
                };
                if !matches {
                    continue;
                }
                let Ok(payload) = serde_json::to_string(&item) else {
                    continue;
                };
                if socket.send(Message::Text(payload)).await.is_err() {
                    break;
                }
            }
        }
    }
}

#[derive(Debug)]
struct ApiError(StatusCode, String);

impl From<ServiceError> for ApiError {
    fn from(value: ServiceError) -> Self {
        match value {
            ServiceError::RunNotFound(_) => Self(StatusCode::NOT_FOUND, value.to_string()),
            ServiceError::MissingPlan(_) => Self(StatusCode::BAD_REQUEST, value.to_string()),
            _ => Self(StatusCode::INTERNAL_SERVER_ERROR, value.to_string()),
        }
    }
}

impl From<ToolboxError> for ApiError {
    fn from(value: ToolboxError) -> Self {
        Self(StatusCode::INTERNAL_SERVER_ERROR, value.to_string())
    }
}

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        (self.0, self.1).into_response()
    }
}

