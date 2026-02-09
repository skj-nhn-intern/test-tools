"""
Nginx 부하 테스트용 Locust 시나리오
- 루트(/) 요청, 정적 리소스, 다양한 경로 테스트
"""
from locust import HttpUser, task, between
import random


class NginxLoadUser(HttpUser):
    """Nginx 서버에 대한 일반적인 웹 사용자 시뮬레이션"""

    # 요청 간 대기 시간 (초) - 실제 사용자처럼 간격을 둠
    wait_time = between(1, 3)

    def on_start(self):
        """각 가상 사용자 시작 시 1회 실행 (선택)"""
        pass

    @task(weight=5)
    def get_root(self):
        """루트(/) 요청 - 가장 빈번한 시나리오"""
        self.client.get("/", name="/")

    @task(weight=3)
    def get_favicon(self):
        """favicon 요청 (브라우저가 자주 요청)"""
        self.client.get("/favicon.ico", name="/favicon.ico")

    @task(weight=2)
    def get_static_asset(self):
        """정적 리소스 패턴 (CSS, JS, 이미지 등)"""
        paths = ["/static/style.css", "/static/script.js", "/images/logo.png"]
        path = random.choice(paths)
        self.client.get(path, name="/static/*")

    @task(weight=1)
    def get_health_or_status(self):
        """헬스체크/상태 엔드포인트 (nginx upstream 확인 등)"""
        self.client.get("/health", name="/health")
        self.client.get("/status", name="/status")

    @task(weight=1)
    def get_with_query(self):
        """쿼리 스트링이 있는 요청"""
        self.client.get("/?cache=bust", name="/?query")
        self.client.get("/api?page=1&size=10", name="/api?query")


class NginxStressUser(HttpUser):
    """고부하 스트레스 테스트용 - 짧은 대기 시간"""

    wait_time = between(0.1, 0.5)

    @task
    def rapid_requests(self):
        self.client.get("/", name="/")
        self.client.get("/favicon.ico", name="/favicon.ico")
