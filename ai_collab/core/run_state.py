"""
Run-scoped state store for tmux orchestration.

This module provides a local control-plane state model:
- run binding metadata
- append-only structured events
- step/agent status snapshots for resume/debug
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import threading
from typing import Any
from uuid import uuid4


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class RunPaths:
    run_id: str
    run_dir: Path
    binding_file: Path
    events_file: Path
    state_file: Path


class RunStateStore:
    """Thread-safe local state/event store for one orchestration run."""

    def __init__(
        self,
        *,
        cwd: Path,
        run_id: str,
        session: str,
        controller_agent: str,
        controller_pane: str,
    ) -> None:
        base = cwd / ".ai-collab" / "runs"
        run_dir = base / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        self.paths = RunPaths(
            run_id=run_id,
            run_dir=run_dir,
            binding_file=run_dir / "binding.json",
            events_file=run_dir / "events.jsonl",
            state_file=run_dir / "state.json",
        )
        self._lock = threading.Lock()
        self._state: dict[str, Any] = {
            "run_id": run_id,
            "label": "",
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
            "session": session,
            "controller": {
                "agent": controller_agent,
                "pane_id": controller_pane,
            },
            "agents": {},
            "steps": {},
        }
        self._write_binding()
        self._write_state()

    @classmethod
    def create(
        cls,
        *,
        cwd: Path,
        session: str,
        controller_agent: str,
        controller_pane: str,
    ) -> "RunStateStore":
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
        return cls(
            cwd=cwd,
            run_id=run_id,
            session=session,
            controller_agent=controller_agent,
            controller_pane=controller_pane,
        )

    @classmethod
    def load(cls, *, cwd: Path, run_id: str) -> "RunStateStore | None":
        run_dir = cwd / ".ai-collab" / "runs" / run_id
        state_file = run_dir / "state.json"
        binding_file = run_dir / "binding.json"
        events_file = run_dir / "events.jsonl"
        if not state_file.exists():
            return None
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None

        self = cls.__new__(cls)
        self.paths = RunPaths(
            run_id=run_id,
            run_dir=run_dir,
            binding_file=binding_file,
            events_file=events_file,
            state_file=state_file,
        )
        self._lock = threading.Lock()
        self._state = state if isinstance(state, dict) else {}
        return self

    @classmethod
    def list_runs(cls, *, cwd: Path, limit: int = 20) -> list[dict[str, Any]]:
        root = cwd / ".ai-collab" / "runs"
        if not root.exists():
            return []
        summaries: list[dict[str, Any]] = []
        for run_dir in root.iterdir():
            if not run_dir.is_dir():
                continue
            run_id = run_dir.name
            state_file = run_dir / "state.json"
            if not state_file.exists():
                continue
            try:
                state = json.loads(state_file.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            if not isinstance(state, dict):
                continue
            controller = state.get("controller", {})
            agent_states = state.get("agents", {})
            step_states = state.get("steps", {})
            summaries.append(
                {
                    "run_id": run_id,
                    "label": str(state.get("label", "")).strip(),
                    "created_at": str(state.get("created_at", "")),
                    "updated_at": str(state.get("updated_at", "")),
                    "session": str(state.get("session", "")),
                    "controller_agent": str(controller.get("agent", "")),
                    "controller_pane": str(controller.get("pane_id", "")),
                    "status": cls._derive_status(agent_states=agent_states, step_states=step_states),
                    "agents": agent_states,
                    "steps": step_states,
                }
            )
        summaries.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        return summaries[: max(1, int(limit))]

    @staticmethod
    def _derive_status(*, agent_states: Any, step_states: Any) -> str:
        agents = agent_states if isinstance(agent_states, dict) else {}
        steps = step_states if isinstance(step_states, dict) else {}
        statuses = {
            str(details.get("status", "")).strip().lower()
            for details in agents.values()
            if isinstance(details, dict)
        }
        if any(state in {"error", "failed", "timeout"} for state in statuses):
            return "degraded"
        if "running" in statuses:
            return "running"
        done_values = {"done", "complete", "completed", "accepted"}
        step_statuses = {
            str(details.get("status", "")).strip().lower()
            for details in steps.values()
            if isinstance(details, dict)
        }
        if step_statuses and step_statuses.issubset(done_values):
            return "completed"
        if agents:
            return "paused"
        return "created"

    def _write_binding(self) -> None:
        payload = {
            "run_id": self.paths.run_id,
            "session": self._state.get("session"),
            "controller": self._state.get("controller", {}),
            "created_at": self._state.get("created_at"),
            "updated_at": self._state.get("updated_at"),
            "label": self._state.get("label", ""),
        }
        self.paths.binding_file.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _write_state(self) -> None:
        self._state["updated_at"] = _utc_now()
        self.paths.state_file.write_text(
            json.dumps(self._state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._write_binding()

    @property
    def run_id(self) -> str:
        return self.paths.run_id

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._state, ensure_ascii=False))

    def set_label(self, *, label: str) -> None:
        with self._lock:
            self._state["label"] = str(label).strip()
            self._write_state()

    def rebind_controller(self, *, session: str, pane_id: str) -> None:
        with self._lock:
            self._state["session"] = session
            controller = self._state.setdefault("controller", {})
            controller["pane_id"] = pane_id
            controller.setdefault("agent", "")
            self._write_state()

    def bind_agent(self, *, agent: str, pane_id: str, step_tickets: list[dict[str, str]]) -> None:
        with self._lock:
            agent_state = self._state.setdefault("agents", {}).setdefault(agent, {})
            agent_state.update(
                {
                    "pane_id": pane_id,
                    "status": "running",
                    "last_event_at": _utc_now(),
                    "step_tickets": step_tickets,
                }
            )
            for ticket in step_tickets:
                step_id = ticket.get("step_id", "").strip()
                if not step_id:
                    continue
                self._state.setdefault("steps", {}).setdefault(
                    step_id,
                    {
                        "agent": agent,
                        "nonce": ticket.get("nonce", ""),
                        "status": "assigned",
                        "updated_at": _utc_now(),
                    },
                )
            self._write_state()

    def set_agent_status(self, *, agent: str, status: str, detail: str = "") -> None:
        with self._lock:
            agent_state = self._state.setdefault("agents", {}).setdefault(agent, {})
            agent_state["status"] = status
            agent_state["detail"] = detail
            agent_state["last_event_at"] = _utc_now()
            self._write_state()

    def set_step_status(
        self,
        *,
        step_id: str,
        status: str,
        agent: str | None = None,
        nonce: str | None = None,
        summary: str | None = None,
    ) -> None:
        with self._lock:
            step = self._state.setdefault("steps", {}).setdefault(step_id, {})
            step["status"] = status
            if agent:
                step["agent"] = agent
            if nonce:
                step["nonce"] = nonce
            if summary:
                step["summary"] = summary
            step["updated_at"] = _utc_now()
            self._write_state()

    def expected_nonce_for_step(self, *, step_id: str) -> str | None:
        with self._lock:
            step = self._state.get("steps", {}).get(step_id, {})
            nonce = str(step.get("nonce", "")).strip()
            return nonce or None

    def append_event(
        self,
        *,
        event_type: str,
        source: str,
        agent: str = "",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        entry = {
            "event_id": uuid4().hex,
            "ts": _utc_now(),
            "run_id": self.paths.run_id,
            "type": event_type,
            "source": source,
            "agent": agent,
            "payload": payload or {},
        }
        with self._lock:
            with self.paths.events_file.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self._state["updated_at"] = entry["ts"]
            self._write_state()
        return entry
