
import json
from pathlib import Path
from types import SimpleNamespace
from ai_collab.cli import _build_controller_prompt_document
from ai_collab.core.config import Config

def test_dynamic_prompt_generates_correct_stages_for_different_blueprints():
    config = Config.create_default()
    
    # Mock result
    result = SimpleNamespace(
        available_agents=[],
        orchestration_plan=[]
    )
    
    # Test with default (auto -> delivery-loop)
    prompt_en = _build_controller_prompt_document(
        task="Test Task",
        controller="codex",
        result=result,
        config=config,
        lang="en-US"
    )
    
    # Extract JSON from prompt
    json_start = prompt_en.find("```json") + 7
    json_end = prompt_en.find("```", json_start)
    steps_json = json.loads(prompt_en[json_start:json_end])
    
    # delivery-loop has 7 stages
    assert len(steps_json['steps']) == 7
    stages = [s['responsibility_stage'] for s in steps_json['steps']]
    assert stages == ["collect", "model", "plan", "execute", "validate", "correct", "deliver"]

    # Test with design-first (-> design-led-loop)
    config.auto_collaboration["default_session_preset"] = "design-first"
    prompt_design = _build_controller_prompt_document(
        task="Test Design Task",
        controller="codex",
        result=result,
        config=config,
        lang="en-US"
    )
    
    json_start = prompt_design.find("```json") + 7
    json_end = prompt_design.find("```", json_start)
    steps_json_design = json.loads(prompt_design[json_start:json_end])
    
    # design-led-loop has 8 stages
    assert len(steps_json_design['steps']) == 8
    stages_design = [s['responsibility_stage'] for s in steps_json_design['steps']]
    assert "artifact" in stages_design

def test_dynamic_prompt_maps_roles_to_leads():
    config = Config.create_default()
    # Explicitly set leads
    config.routing["intent_preferences"]["architecture"] = ["gemini"]
    config.routing["intent_preferences"]["implementation"] = ["codex"]
    config.routing["intent_preferences"]["testing"] = ["claude"]
    
    result = SimpleNamespace(
        available_agents=[],
        orchestration_plan=[]
    )
    
    prompt = _build_controller_prompt_document(
        task="Test Task",
        controller="codex",
        result=result,
        config=config,
        lang="en-US"
    )
    
    json_start = prompt.find("```json") + 7
    json_end = prompt.find("```", json_start)
    steps_json = json.loads(prompt[json_start:json_end])
    
    # S1 in delivery-loop is collect-context (default_agent=codex)
    # S2 is model-system (default_agent=gemini)
    # S5 is validate-result (default_agent=claude)
    
    owners = {s['id']: s['owner'] for s in steps_json['steps']}
    assert owners['S1'] == "codex"
    assert owners['S2'] == "gemini"
    assert owners['S5'] == "claude"
