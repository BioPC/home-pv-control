"""Run the dependency-free foundation suite with workspace-local temporary files."""

from pathlib import Path
import json
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TEMP = ROOT / "work" / "foundation-test-temp"
TEMP.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = str(TEMP)
if __name__ == "__main__":
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests" / "foundation"))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(
        json.dumps(
            {
                "tests_run": result.testsRun,
                "failures": len(result.failures),
                "errors": len(result.errors),
                "successful": result.wasSuccessful(),
            }
        )
    )
    sys.exit(not result.wasSuccessful())
