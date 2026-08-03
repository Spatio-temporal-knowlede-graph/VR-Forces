import sys
from pathlib import Path

# 패키지 루트를 import 경로에 넣는다. 경로에 공백과 한글이 있어 설치 방식
# 대신 sys.path 주입을 쓴다(선행 프로젝트와 동일).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vtmak.scnx.pack import ensure_golden  # noqa: E402


def pytest_sessionstart(session):
    """golden .scnx는 yewon_test/ 디렉터리에서 파생되므로 저장소에 두지 않는다.
    테스트가 필요로 하니 세션 시작 때 만들어 둔다."""
    ensure_golden(Path(__file__).resolve().parents[1] / "yewon_test")
