"""Pytest path bootstrap for the OTA agent test suite.
OTA 代理测试套件的 Pytest 路径引导。
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
