"""
시나리오 3: 동시 접속자가 공유·사설(개인) 모두 접속
- 공유 링크 접근 + 로그인 후 개인 앨범/사진 조회 혼합
- 다운로드 기능 제외
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scenarios._scenario_base as _scenario_base


class Scenario3MixedUser(_scenario_base.ScenarioBaseUser):
    """시나리오 3: 공유(shared) + 사설(private) 혼합 접속. 동일 태스크 세트, 비율은 베이스 유지."""
    pass


