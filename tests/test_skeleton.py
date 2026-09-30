import importlib
import pkgutil

PACKAGES = ["config", "contracts", "ingest", "build", "features", "labels",
            "models", "evaluation", "pipelines", "execution"]


def test_all_modules_import_and_have_docstrings():
    for name in PACKAGES:
        pkg = importlib.import_module(name)
        assert pkg.__doc__
        for info in pkgutil.walk_packages(pkg.__path__, prefix=name + "."):
            mod = importlib.import_module(info.name)
            assert mod.__doc__, info.name
