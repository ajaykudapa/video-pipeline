import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "worker", ROOT / "autoscaler"):
    sys.path.insert(0, str(p))
