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
