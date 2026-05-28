from ai_collab.core.workflow_v2 import (
    WorkflowBlueprintV2,
    builtin_session_presets,
    builtin_workflow_blueprints,
    find_session_preset_for_workflow_blueprint,
    resolve_session_preset,
    resolve_workflow_blueprint,
)


def test_builtin_session_presets_expose_user_facing_presets() -> None:
    presets = builtin_session_presets()

    assert "auto" in presets
    assert "quick-delivery" in presets
    assert "design-first" in presets
    assert "debug-priority" in presets
    assert "research-priority" in presets
    assert "validation-first" in presets
    assert "document-first" in presets


def test_quick_delivery_preset_maps_to_delivery_loop() -> None:
    preset = resolve_session_preset("quick-delivery")

    assert preset.workflow_key == "delivery-loop"
    assert preset.user_visible is True


def test_design_first_preset_prefers_design_led_loop() -> None:
    preset = resolve_session_preset("design-first")

    assert preset.workflow_key == "design-led-loop"
    assert "mockup" in preset.preferred_artifacts


def test_validation_first_preset_prefers_validation_loop() -> None:
    preset = resolve_session_preset("validation-first")

    assert preset.workflow_key == "validation-loop"


def test_document_first_preset_prefers_document_loop() -> None:
    preset = resolve_session_preset("document-first")

    assert preset.workflow_key == "document-loop"


def test_find_matching_session_preset_for_workflow_blueprint() -> None:
    assert find_session_preset_for_workflow_blueprint("validation-loop") == "validation-first"
    assert find_session_preset_for_workflow_blueprint("delivery-loop") == "auto"


def test_builtin_workflow_blueprints_include_v2_core_loops() -> None:
    blueprints = builtin_workflow_blueprints()

    assert set(blueprints) >= {
        "delivery-loop",
        "design-led-loop",
        "diagnose-loop",
        "research-loop",
        "validation-loop",
        "document-loop",
    }


def test_delivery_loop_uses_stage_based_semantics() -> None:
    workflow = resolve_workflow_blueprint("delivery-loop")

    assert isinstance(workflow, WorkflowBlueprintV2)
    assert [stage.responsibility_stage for stage in workflow.stages] == [
        "collect",
        "model",
        "plan",
        "execute",
        "validate",
        "correct",
        "deliver",
    ]


def test_design_led_loop_has_explicit_artifact_stage() -> None:
    workflow = resolve_workflow_blueprint("design-led-loop")

    artifact_stage = next(stage for stage in workflow.stages if stage.responsibility_stage == "artifact")

    assert "contract" in artifact_stage.allowed_artifacts
    assert "mockup" in artifact_stage.allowed_artifacts


def test_diagnose_loop_requires_correction_stage() -> None:
    workflow = resolve_workflow_blueprint("diagnose-loop")

    assert workflow.supports_correction is True
    assert workflow.stages[-2].responsibility_stage == "correct"
