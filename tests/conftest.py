import sys
from pathlib import Path


def pytest_sessionstart(session):
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / 'configtool-client'))
    sys.path.insert(0, str(root / 'configtool-secrets'))