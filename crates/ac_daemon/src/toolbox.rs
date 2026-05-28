use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use thiserror::Error;
use tokio::process::Command;

#[derive(Debug, Error)]
pub enum ToolboxError {
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
}

#[derive(Debug, Clone, Default)]
pub struct LocalToolbox;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ShellToolRequest {
    pub command: String,
    pub cwd: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ShellToolResponse {
    pub exit_code: Option<i32>,
    pub stdout: String,
    pub stderr: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FsReadRequest {
    pub path: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FsReadResponse {
    pub content: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SearchToolRequest {
    pub root: String,
    pub pattern: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SearchToolResponse {
    pub matches: Vec<String>,
}

impl LocalToolbox {
    pub async fn shell(&self, request: ShellToolRequest) -> Result<ShellToolResponse, ToolboxError> {
        let mut command = Command::new("zsh");
        command.arg("-lc").arg(request.command);
        if let Some(cwd) = request.cwd {
            command.current_dir(cwd);
        }
        let output = command.output().await?;
        Ok(ShellToolResponse {
            exit_code: output.status.code(),
            stdout: String::from_utf8_lossy(&output.stdout).to_string(),
            stderr: String::from_utf8_lossy(&output.stderr).to_string(),
        })
    }

    pub async fn read_text(&self, request: FsReadRequest) -> Result<FsReadResponse, ToolboxError> {
        let content = tokio::fs::read_to_string(request.path).await?;
        Ok(FsReadResponse { content })
    }

    pub async fn search(&self, request: SearchToolRequest) -> Result<SearchToolResponse, ToolboxError> {
        let output = Command::new("rg")
            .arg("-n")
            .arg("--no-heading")
            .arg("--color")
            .arg("never")
            .arg(request.pattern)
            .arg(PathBuf::from(request.root))
            .output()
            .await?;
        Ok(SearchToolResponse {
            matches: String::from_utf8_lossy(&output.stdout)
                .lines()
                .map(str::to_owned)
                .collect(),
        })
    }
}

