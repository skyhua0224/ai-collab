#!/usr/bin/env python3
"""
测试健康检查功能
"""

import subprocess
from ai_collab.core.config import Config
from ai_collab.core.environment import resolve_executable

def test_health_check(provider: str):
    """测试单个 provider 的健康检查"""
    config = Config.load()
    provider_config = config.providers.get(provider)

    if not provider_config:
        print(f"{provider}: Provider not configured")
        return

    executable = resolve_executable(provider_config.cli)
    if not executable:
        print(f"{provider}: Executable not found: {provider_config.cli}")
        return

    # 测试 --version
    cmd = [executable, "--version"]
    print(f"\n{provider}: Testing command: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        print(f"  Return code: {result.returncode}")
        print(f"  Stdout: {result.stdout[:200]}")
        print(f"  Stderr: {result.stderr[:200]}")

        if result.returncode == 0 or result.stdout or result.stderr:
            print(f"  ✓ Health check passed")
        else:
            print(f"  ✗ Health check failed: No output")
    except subprocess.TimeoutExpired:
        print(f"  ✗ Timeout after 3s")
    except Exception as e:
        print(f"  ✗ Error: {e}")

if __name__ == "__main__":
    for provider in ["codex", "claude", "gemini"]:
        test_health_check(provider)
