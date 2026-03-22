from __future__ import annotations

import sys
from pathlib import Path


CURRENT_DIR = Path(__file__).resolve().parent
API_DIR = CURRENT_DIR / "api"

if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from app.fake_sensor_device import main


if __name__ == "__main__":
    raise SystemExit(main())
