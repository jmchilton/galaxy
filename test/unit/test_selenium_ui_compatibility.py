"""Compatibility of test-framework imports after lifting reusable UI helpers."""


def test_upload_test_imports_reuse_core_helpers():
    from galaxy.selenium import upload_activity_helpers as core
    from galaxy_test.selenium import upload_activity_helpers as legacy

    for name in vars(legacy):
        if not name.startswith("_"):
            assert getattr(legacy, name) is getattr(core, name)


def test_legacy_gxui_client_still_launches():
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "galaxy_test.selenium.gxui.client", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "gxui start" in result.stdout
