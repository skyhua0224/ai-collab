#!/usr/bin/env python3
"""
Quick validation script for ai-collab package.
Tests basic functionality without full installation.
"""

import sys
from pathlib import Path

# Add package to path for testing
sys.path.insert(0, str(Path(__file__).parent))

def test_imports():
    """Test that all modules can be imported."""
    print("Testing imports...")

    try:
        from ai_collab import Config, CollaborationDetector, ModelSelector
        print("✅ Main package imports successful")
    except ImportError as e:
        print(f"❌ Import error: {e}")
        return False

    try:
        from ai_collab.core.config import Config, ProviderConfig, QualityGateConfig
        from ai_collab.core.detector import CollaborationDetector, CollaborationResult
        from ai_collab.core.selector import ModelSelector, ModelSelectionResult
        from ai_collab.core.workflow import WorkflowManager, Workflow, WorkflowPhase
        print("✅ Core modules imports successful")
    except ImportError as e:
        print(f"❌ Core module import error: {e}")
        return False

    return True


def test_config():
    """Test configuration creation."""
    print("\nTesting configuration...")

    try:
        from ai_collab.core.config import Config

        config = Config.create_default()
        assert config.version == "1.0"
        assert config.current_controller == "claude"
        assert len(config.providers) == 3
        assert config.quality_gate.enabled is True

        print("✅ Configuration creation successful")
        return True
    except Exception as e:
        print(f"❌ Configuration test error: {e}")
        return False


def test_detector():
    """Test collaboration detector."""
    print("\nTesting collaboration detector...")

    try:
        from ai_collab.core.config import Config
        from ai_collab.core.detector import CollaborationDetector

        config = Config.create_default()
        config.auto_collaboration = {
            "enabled": True,
            "triggers": [
                {
                    "name": "test",
                    "description": "Test trigger",
                    "patterns": ["test"],
                    "primary": "claude",
                    "reviewers": ["codex"],
                    "workflow": "test-workflow",
                }
            ],
        }
        config.workflows = {
            "test-workflow": {
                "description": "Test workflow",
                "phases": [
                    {"agent": "claude", "action": "test", "output": "result"}
                ],
            }
        }

        detector = CollaborationDetector(config)
        result = detector.detect("test task", "claude")

        # Should detect collaboration
        assert result.need_collaboration is True
        assert result.trigger == "test"

        print("✅ Collaboration detector working")
        return True
    except Exception as e:
        print(f"❌ Detector test error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_selector():
    """Test model selector."""
    print("\nTesting model selector...")

    try:
        from ai_collab.core.config import Config
        from ai_collab.core.selector import ModelSelector

        config = Config.create_default()
        selector = ModelSelector(config)

        result = selector.select_model("claude", "test task", "default")
        assert result.model is not None
        assert result.cli is not None

        print("✅ Model selector working")
        return True
    except Exception as e:
        print(f"❌ Selector test error: {e}")
        return False


def main():
    """Run all validation tests."""
    print("=" * 60)
    print("AI Collaboration System - Validation")
    print("=" * 60)

    tests = [
        test_imports,
        test_config,
        test_detector,
        test_selector,
    ]

    results = []
    for test in tests:
        results.append(test())

    print("\n" + "=" * 60)
    if all(results):
        print("✅ All validation tests passed!")
        print("=" * 60)
        return 0
    else:
        print("❌ Some validation tests failed")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())
