use ac_engine::{build_p1_contract_fixture, p1_contract_schemas};
use serde_json::Value;
use std::env;
use std::fs;
use std::path::{Path, PathBuf};

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .canonicalize()
        .expect("repo root")
}

fn pretty(value: &Value) -> String {
    serde_json::to_string_pretty(value).expect("pretty json")
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let target = env::args()
        .nth(1)
        .map(PathBuf::from)
        .unwrap_or_else(|| repo_root().join("contracts/vnext"));

    let schemas_dir = target.join("schemas");
    let mock_dir = target.join("mock");
    fs::create_dir_all(&schemas_dir)?;
    fs::create_dir_all(&mock_dir)?;

    for (filename, schema) in p1_contract_schemas() {
        fs::write(schemas_dir.join(filename), pretty(&schema))?;
    }

    let fixture = build_p1_contract_fixture()?;
    let projection = serde_json::to_value(&fixture.projection)?;
    fs::write(mock_dir.join("run_projection.json"), pretty(&projection))?;

    let events = fixture
        .events
        .iter()
        .map(serde_json::to_string)
        .collect::<Result<Vec<_>, _>>()?
        .join("\n")
        + "\n";
    fs::write(mock_dir.join("run_events.jsonl"), events)?;

    Ok(())
}
