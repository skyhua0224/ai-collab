use ac_engine::{build_p1_contract_fixture, p1_contract_schemas};
use serde::Serialize;
use serde_json::Value;
use std::fs;
use std::path::{Path, PathBuf};

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .canonicalize()
        .expect("repo root")
}

fn normalize_json_string<T: Serialize>(value: &T) -> String {
    let parsed: Value = serde_json::to_value(value).expect("to value");
    serde_json::to_string_pretty(&parsed).expect("pretty json")
}

#[test]
fn checked_in_contract_assets_match_generated_versions() {
    let root = repo_root();
    let contracts_dir = root.join("contracts/vnext");
    let schemas_dir = contracts_dir.join("schemas");
    let mock_dir = contracts_dir.join("mock");

    for (filename, schema) in p1_contract_schemas() {
        let actual = fs::read_to_string(schemas_dir.join(filename)).expect("read schema file");
        let expected = normalize_json_string(&schema);
        assert_eq!(
            serde_json::from_str::<Value>(&actual).unwrap(),
            serde_json::from_str::<Value>(&expected).unwrap(),
            "schema drift in {filename}"
        );
    }

    let fixture = build_p1_contract_fixture().expect("build contract fixture");
    let actual_projection =
        fs::read_to_string(mock_dir.join("run_projection.json")).expect("read projection");
    let expected_projection = normalize_json_string(&fixture.projection);
    assert_eq!(
        serde_json::from_str::<Value>(&actual_projection).unwrap(),
        serde_json::from_str::<Value>(&expected_projection).unwrap(),
        "projection drift"
    );

    let actual_events = fs::read_to_string(mock_dir.join("run_events.jsonl")).expect("read events");
    let expected_events = fixture
        .events
        .iter()
        .map(|event| serde_json::to_string(event).expect("serialize event"))
        .collect::<Vec<_>>()
        .join("\n")
        + "\n";
    assert_eq!(actual_events, expected_events, "event fixture drift");
}
