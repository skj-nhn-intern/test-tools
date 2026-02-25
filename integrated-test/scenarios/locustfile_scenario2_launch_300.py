"""
시나리오 2: 사전 예약자 300명 서비스 출시
- 동시 접속자 300명, 불규칙적으로 요청 전송
- 동시 접속 유지 (부하 형태: 출시 직후 러시)
"""

import sys
from pathlib import Path

from locust import between

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scenarios._scenario_base as _scenario_base
from locust import LoadTestShape


class Scenario2LaunchUser(_scenario_base.ScenarioBaseUser):
    """시나리오 2: 불규칙 대기 시간으로 요청 전송 (0.2~4초)."""
    wait_time = between(0.2, 4.0)


class Launch300Shape(LoadTestShape):
    """
    사전 예약 300명 출시: 불규칙하게 300명까지 증가 후 유지.
    - 0~60초: 0 → 300명 (초당 약 5명 spawn)
    - 60초~: 300명 유지
    """
    stages = [
        {"duration": 60, "users": 300, "spawn_rate": 5},
        {"duration": 3600, "users": 300, "spawn_rate": 300},
    ]

    def tick(self):
        run_time = self.get_run_time()
        if run_time < self.stages[0]["duration"]:
            return (self.stages[0]["users"], self.stages[0]["spawn_rate"])
        if run_time < self.stages[1]["duration"]:
            return (self.stages[1]["users"], self.stages[1]["spawn_rate"])
        return None
