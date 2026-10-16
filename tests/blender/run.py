"""Spustí Blender testy (test_*.py) a zapíše výsledky do JSON.

    blender --background --factory-startup --python tests/blender/run.py -- \
        --repo <repo> --project <pracovní projekt> --out <výsledky.json>

Addon se registruje přímo ze zdrojáků v repu, ne z nainstalované kopie.
"""

import json
import os
import sys
import traceback
import unittest

args = sys.argv[sys.argv.index("--") + 1:]
options = dict(zip(args[::2], args[1::2]))
HERE = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, os.path.join(options["--repo"], "tools"))
sys.path.insert(0, HERE)

results = []
try:
    import blender_bridge
    blender_bridge.register()
    import harness
    harness.configure(options["--project"])

    class Collect(unittest.TestResult):
        def _add(self, test, status, message=""):
            results.append({"name": test.id(), "status": status, "message": message})

        def addSuccess(self, test):
            self._add(test, "pass")

        def addFailure(self, test, err):
            self._add(test, "fail", str(err[1]).splitlines()[0][:400])
            print(self._exc_info_to_string(err, test))

        def addError(self, test, err):
            self._add(test, "fail", "%s: %s" % (err[0].__name__, str(err[1])[:400]))
            print(self._exc_info_to_string(err, test))

        def addSkip(self, test, reason):
            self._add(test, "skip", reason)

    suite = unittest.defaultTestLoader.discover(HERE, pattern="test_*.py")
    suite.run(Collect())
except Exception:
    traceback.print_exc()
    results.append({"name": "(načtení addonu)", "status": "fail", "message": traceback.format_exc(limit=1)})

with open(options["--out"], "w", encoding="utf-8") as handle:
    json.dump(results, handle, indent=2, ensure_ascii=False)
