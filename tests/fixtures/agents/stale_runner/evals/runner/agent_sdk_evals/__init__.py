"""A deliberately out-of-date runner copy (0.0.1) for the DEP/CFG050 tests.

This is not the real runner. It is the two files `inspect_runner_copy` reads —
`VERSION` and the package marker — pinned one version behind what the plugin
ships, so `check_runner.py` reports DEP001, `install_runner.py` refuses without
`--upgrade`, and `validate_config.py` reports CFG050 for the config that
declares the same stale version.

Do not update this file. Its staleness is the fixture.
"""

__version__ = "0.0.1"
