"""Compatibility entry point for python -m galaxy_test.selenium.gxui.client."""

from galaxy.selenium.gxui.client import main as main

if __name__ == "__main__":
    raise SystemExit(main())
