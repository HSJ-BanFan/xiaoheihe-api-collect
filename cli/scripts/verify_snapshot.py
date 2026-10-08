"""Verify the package snapshot without consulting case files or the network."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from xhh_sdk.routes import check_snapshot


if __name__ == "__main__":
    print(json.dumps(check_snapshot(), indent=2))
