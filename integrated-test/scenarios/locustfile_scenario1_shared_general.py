"""
시나리오 1: 전반적인 공유 테스트
- 동시 접속자 100명 기준
- 사용자 로그인 및 로그아웃, 앨범 추가·삭제, 이미지 업로드
- 공유 링크 생성·접속·공유 링크 삭제
- 타당하지 않은 접속 포함 (잘못된 토큰, 잘못된 로그인)
- 다운로드 기능 제외
"""

import sys
from pathlib import Path

# integrated-test를 path에 넣어 scenarios 패키지 로드 (베이스는 모듈로만 참조해 Locust가 중복 유저로 인식하지 않도록)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scenarios._scenario_base as _scenario_base


class Scenario1SharedGeneralUser(_scenario_base.ScenarioBaseUser):
    """시나리오 1: 100명 동시 접속, 공유·앨범·업로드·부정접근 전반."""
    pass


