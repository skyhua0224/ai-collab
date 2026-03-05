from __future__ import annotations

import json

from ai_collab.core.run_state import RunStateStore


def test_run_state_store_writes_binding_state_and_events(tmp_path) -> None:
    store = RunStateStore.create(
        cwd=tmp_path,
        session="s1",
        controller_agent="codex",
        controller_pane="%1",
    )
    store.bind_agent(
        agent="claude",
        pane_id="%2",
        step_tickets=[{"step_id": "S2", "nonce": "n2"}],
    )
    store.set_step_status(step_id="S2", status="done", agent="claude", nonce="n2", summary="ok")
    event = store.append_event(
        event_type="step_done",
        source="subagent_event",
        agent="claude",
        payload={"step_id": "S2"},
    )

    binding = json.loads(store.paths.binding_file.read_text(encoding="utf-8"))
    state = json.loads(store.paths.state_file.read_text(encoding="utf-8"))
    lines = store.paths.events_file.read_text(encoding="utf-8").splitlines()

    assert binding["run_id"] == store.run_id
    assert state["steps"]["S2"]["status"] == "done"
    assert event["type"] == "step_done"
    assert len(lines) >= 1


def test_run_state_store_load_list_and_rebind(tmp_path) -> None:
    store = RunStateStore.create(
        cwd=tmp_path,
        session="s1",
        controller_agent="codex",
        controller_pane="%1",
    )
    store.bind_agent(
        agent="gemini",
        pane_id="%3",
        step_tickets=[{"step_id": "S3", "nonce": "n3"}],
    )

    loaded = RunStateStore.load(cwd=tmp_path, run_id=store.run_id)
    assert loaded is not None
    loaded.set_label(label="nightly-rollback")
    loaded.rebind_controller(session="s2", pane_id="%9")

    state = loaded.snapshot()
    assert state["label"] == "nightly-rollback"
    assert state["session"] == "s2"
    assert state["controller"]["pane_id"] == "%9"

    items = RunStateStore.list_runs(cwd=tmp_path, limit=10)
    assert items
    assert items[0]["run_id"] == store.run_id
    assert items[0]["status"] in {"running", "paused", "created", "completed", "degraded"}
