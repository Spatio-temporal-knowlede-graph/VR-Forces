import sys
from pathlib import Path

# 패키지 루트를 import 경로에 넣는다. 경로에 공백과 한글이 있어 설치 방식
# 대신 sys.path 주입을 쓴다(선행 프로젝트와 동일).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
