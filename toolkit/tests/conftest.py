"""시험 모듈보다 먼저 서버 소스 폴더를 import 경로 맨 앞에 넣는다: 소스로 넣은 업스트림(src/hwpx_automation)을 시험하게."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins" / "hyeyum-hwpx" / "server" / "src"))
