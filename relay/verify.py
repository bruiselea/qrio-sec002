"""Run all relay tests without network, BLE, firmware or owner credentials."""
from pathlib import Path
import unittest

if __name__ == '__main__':
    tests = unittest.defaultTestLoader.discover(str(Path(__file__).with_name('tests')))
    result = unittest.TextTestRunner(verbosity=2).run(tests)
    raise SystemExit(0 if result.wasSuccessful() else 1)
