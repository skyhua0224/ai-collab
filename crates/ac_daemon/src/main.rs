use ac_daemon::{build_router, RunService};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut addr = "127.0.0.1:8787".to_owned();
    let mut state_dir = ".ai-collab/vnext/runs".to_owned();

    let mut args = std::env::args().skip(1);
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--addr" => {
                if let Some(value) = args.next() {
                    addr = value;
                }
            }
            "--state-dir" => {
                if let Some(value) = args.next() {
                    state_dir = value;
                }
            }
            _ => {}
        }
    }

    let service = RunService::new(state_dir).await?;
    let listener = tokio::net::TcpListener::bind(&addr).await?;
    println!("ai-collabd listening on {}", listener.local_addr()?);
    axum::serve(listener, build_router(service))
        .with_graceful_shutdown(async {
            let _ = tokio::signal::ctrl_c().await;
        })
        .await?;
    Ok(())
}

