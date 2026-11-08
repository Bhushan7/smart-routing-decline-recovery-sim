import importlib

import pytest


@pytest.mark.parametrize("pkg", ["simulator", "routers", "agent", "analysis", "app"])
def test_packages_importable(pkg):
    importlib.import_module(f"src.{pkg}")
