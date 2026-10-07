"""Compatibility of test-framework imports after lifting reusable UI helpers."""


def test_upload_test_imports_reuse_core_helpers():
    from galaxy.selenium import upload_activity_helpers as core
    from galaxy_test.selenium import upload_activity_helpers as legacy

    for name in vars(legacy):
        if not name.startswith("_"):
            assert getattr(legacy, name) is getattr(core, name)
