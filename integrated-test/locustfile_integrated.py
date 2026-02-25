"""
Nginx 통합 부하 테스트 — Load Balancer → Nginx → Load Balancer → Backend
==========================================================================
대상 구성:
  - Load Balancer → Nginx → Load Balancer → Backend
  - Nginx는 웹 서빙도 하지만 /api 엔드포인트를 통해 백엔드에 접속 가능
  - SPA 정적 서빙: /, /share/{token}, JS/CSS/ICO
  - 리버스 프록시: /api/* → photo_api_backend

사용법 (단계별로 Users를 올려가며 천장을 찾기):
  # 기본 (대화형)
  python3 -m locust -f locustfile_integrated.py --host http://<nginx-host>

  # 헤드리스 + 단일 테스트 유저 (환경변수로 계정 지정)
  LOADTEST_EMAIL=user@example.com LOADTEST_PASSWORD=password123 \
    python3 -m locust -f locustfile_integrated.py --headless \
    -u 200 -r 40 --run-time 5m \
    --host http://<nginx-host> \
    --csv=integrated_result

  # 미리 발급한 토큰 사용 (로그인 생략)
  LOADTEST_TOKEN=eyJ... python3 -m locust -f locustfile_integrated.py --headless ...

  # StepLoadShape 사용 (자동 단계별 부하 증가)
  python3 -m locust -f locustfile_integrated.py --headless \
    --host http://<nginx-host> \
    --csv=integrated_step

멈추는 기준:
  - P95 > 300ms (Nginx 프록시 + Backend 응답 시간)
  - 에러율(404 제외) > 1%
  - CPU > 85%
  - Connection Pool Waiting > 10
"""

import os
import random
import sys
import time
from pathlib import Path

import requests
from locust import HttpUser, task, between, tag

# common 모듈 import (프로젝트 루트 기준)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from common.image_upload_helper import load_image_list
    from common.user_list_helper import load_user_list
except ImportError:
    def load_image_list():
        return []
    def load_user_list():
        return []

# 테스트용 실제 이미지 목록 (UPLOAD_IMAGE_DIR 또는 UPLOAD_IMAGE_LIST 설정 시 사용)
IMAGE_LIST = load_image_list()
# 업로드 필수: 이미지 없을 때 사용할 최소 JPEG (1x1px)
MINIMAL_JPEG = bytes([0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46, 0x00, 0x01, 0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0xFF, 0xDB, 0x00, 0x43, 0x00, 0x08, 0x06, 0x06, 0x07, 0x06, 0x05, 0x08, 0x07, 0x07, 0x07, 0x09, 0x09, 0x08, 0x0A, 0x0C, 0x14, 0x0D, 0x0C, 0x0B, 0x0B, 0x0C, 0x19, 0x12, 0x13, 0x0F, 0x14, 0x1D, 0x1A, 0x1F, 0x1E, 0x1D, 0x1A, 0x1C, 0x1C, 0x20, 0x24, 0x2E, 0x27, 0x20, 0x22, 0x2C, 0x23, 0x1C, 0x1C, 0x28, 0x37, 0x29, 0x2C, 0x30, 0x31, 0x34, 0x34, 0x34, 0x1F, 0x27, 0x39, 0x3D, 0x38, 0x32, 0x3C, 0x2E, 0x33, 0x34, 0x32, 0xFF, 0xC0, 0x00, 0x0B, 0x08, 0x00, 0x01, 0x00, 0x01, 0x01, 0x01, 0x11, 0x00, 0xFF, 0xC4, 0x00, 0x1F, 0x00, 0x00, 0x01, 0x05, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B, 0xFF, 0xDA, 0x00, 0x0C, 0x03, 0x01, 0x00, 0x02, 0x11, 0x03, 0x11, 0x00, 0x3F, 0x00, 0xFB, 0xD9])
# 테스트용 계정 목록 (UPLOAD_USER_LIST 설정 시 사용, 가상 유저별로 한 계정씩 할당)
USER_LIST = load_user_list()
# 계정 할당용 라운드로빈 인덱스 (gevent 단일 스레드에서 증가)
_user_index = [0]


def load_share_token_list() -> list:
    """
    환경변수 SHARE_TOKEN_LIST 파일에서 공유 링크 토큰 목록을 로드합니다.
    반환: [token1, token2, ...]
    """
    path = os.environ.get("SHARE_TOKEN_LIST", "").strip()
    if not path:
        return []
    p = Path(path).resolve()
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line:  # 빈 줄이 아닌 경우
            out.append(line)
    return out


# 공유 링크 토큰 목록 (SHARE_TOKEN_LIST 설정 시 사용)
SHARE_TOKEN_LIST = load_share_token_list()
# 공유 링크 할당용 라운드로빈 인덱스
_share_token_index = [0]


def get_auth_headers(user: "IntegratedNginxUser") -> dict:
    """현재 유저의 Authorization 헤더 (토큰 없으면 빈 dict)."""
    if getattr(user, "token", None):
        return {"Authorization": f"Bearer {user.token}"}
    return {}


class IntegratedNginxUser(HttpUser):
    """
    통합 부하 테스트 유저
    - Nginx를 통해 정적 파일 서빙과 API 프록시 모두 테스트
    - 시작 시 로그인하여 JWT 발급 (또는 환경변수 토큰 사용)
    - task 비율: 실제 사용자 패턴 반영 (읽기 위주, 쓰기는 소량)
    """
    wait_time = between(0.5, 1.5)

    def on_start(self):
        """시작 시 토큰 설정: 환경변수 토큰 우선, UPLOAD_USER_LIST 있으면 그 계정 중 하나로 로그인 시도, 로그인 실패 시 자동 회원가입. 로그인 성공 시 자동으로 앨범 생성 후 공유 링크 발급."""
        self.token = os.environ.get("LOADTEST_TOKEN")
        self.share_token = None  # 공유 링크는 자동으로 발급받음
        self.upload_album_id = None  # 업로드 시 사용할 앨범 ID (on_start에서 생성한 앨범)

        if not self.token:
            if USER_LIST:
                idx = _user_index[0] % len(USER_LIST)
                _user_index[0] += 1
                email, password = USER_LIST[idx]
                username = email.split("@")[0]
            else:
                email = os.environ.get("LOADTEST_EMAIL", "loadtest@example.com")
                password = os.environ.get("LOADTEST_PASSWORD", "loadtest123")
                username = os.environ.get("LOADTEST_USERNAME", email.split("@")[0])

            # Nginx를 통해 /api 경로로 로그인
            with self.client.post(
                "/api/auth/login",
                json={"email": email, "password": password},
                name="POST /api/auth/login (on_start)",
                catch_response=True,
            ) as r:
                if r.status_code == 200:
                    try:
                        self.token = r.json().get("access_token")
                        r.success()
                    except Exception:
                        self.token = None
                        r.failure("invalid login response")
                else:
                    r.failure(f"status {r.status_code}")

            # 로그인 실패 시: 자동으로 회원가입 시도 (USER_LIST 사용 중이어도 등록)
            if not self.token:
                with self.client.post(
                    "/api/auth/register",
                    json={
                        "email": email,
                        "username": username,
                        "password": password,
                    },
                    name="POST /api/auth/register (on_start)",
                    catch_response=True,
                ) as r:
                    if r.status_code in [200, 201]:
                        r.success()
                        with self.client.post(
                            "/api/auth/login",
                            json={"email": email, "password": password},
                            name="POST /api/auth/login (after_register)",
                            catch_response=True,
                        ) as login_r:
                            if login_r.status_code == 200:
                                try:
                                    self.token = login_r.json().get("access_token")
                                    login_r.success()
                                except Exception:
                                    self.token = None
                                    login_r.failure("invalid login response")
                            else:
                                login_r.failure(f"status {login_r.status_code}")
                    else:
                        r.failure(f"status {r.status_code}")

        # 로그인 성공 시: 업로드용 앨범 생성 후, 공유 링크용 앨범 생성 (앨범 제대로 생성·연결)
        if self.token:
            self._ensure_upload_album()
            self._ensure_share_token()

        # 로그인/등록 실패해도 계속 진행 (인증 필요한 태스크만 실패)

    def _ensure_upload_album(self):
        """업로드 전용 앨범 생성, self.upload_album_id 설정. (업로드는 항상 이 앨범에 연결)"""
        with self.client.post(
            "/api/albums/",
            headers=get_auth_headers(self),
            json={
                "name": "LoadTest Upload Album",
                "description": "For photo upload test",
            },
            name="POST /api/albums/ (on_start upload)",
            catch_response=True,
        ) as r:
            if r.status_code not in [200, 201]:
                return
            try:
                album = r.json()
                aid = album.get("id") if isinstance(album, dict) else getattr(album, "id", None)
            except Exception:
                return
            if aid is not None:
                self.upload_album_id = aid

    def _ensure_share_token(self):
        """앨범 생성 후 공유 링크 생성, self.share_token 및 self.upload_album_id 설정."""
        with self.client.post(
            "/api/albums/",
            headers=get_auth_headers(self),
            json={
                "name": "LoadTest Share Album",
                "description": "For shared link test",
            },
            name="POST /api/albums/ (on_start share)",
            catch_response=True,
        ) as r:
            if r.status_code not in [200, 201]:
                return
            try:
                album = r.json()
                album_id = album.get("id") if isinstance(album, dict) else getattr(album, "id", None)
            except Exception:
                return
            if album_id is None:
                return
            self.upload_album_id = album_id  # 실제 업로드 시 이 앨범 사용
        with self.client.post(
            f"/api/albums/{album_id}/share",
            headers={**get_auth_headers(self), "Content-Type": "application/json"},
            json={},
            name="POST /api/albums/{id}/share (on_start)",
            catch_response=True,
        ) as r:
            if r.status_code not in [200, 201]:
                return
            try:
                data = r.json()
                token = data.get("token") if isinstance(data, dict) else getattr(data, "token", None)
                if token:
                    self.share_token = token
            except Exception:
                pass

    # ──────────────────────────────────────────
    # SPA 정적 서빙 (Nginx가 직접 처리)
    # ──────────────────────────────────────────

    @tag("static")
    @task(8)
    def spa_index(self):
        """SPA index.html — 가장 빈번한 요청"""
        with self.client.get(
            "/",
            name="GET /  (SPA index)",
            catch_response=True,
        ) as r:
            self._check_status(r)

    @tag("static")
    @task(5)
    def spa_js(self):
        """JS 번들 — SPA에서 가장 큰 정적 파일 (404면 성공 처리, 선택 리소스)"""
        with self.client.get(
            "/assets/index.js",
            name="GET /assets/*.js",
            catch_response=True,
        ) as r:
            if r.status_code in (200, 404):
                r.success()
            else:
                r.failure(f"status {r.status_code}")

    @tag("static")
    @task(3)
    def spa_css(self):
        """CSS 파일 (404면 성공 처리, 선택 리소스)"""
        with self.client.get(
            "/assets/style.css",
            name="GET /assets/*.css",
            catch_response=True,
        ) as r:
            if r.status_code in (200, 404):
                r.success()
            else:
                r.failure(f"status {r.status_code}")

    @tag("static")
    @task(2)
    def favicon(self):
        """favicon (404면 성공 처리, 선택 리소스)"""
        with self.client.get(
            "/favicon.ico",
            name="GET /favicon.ico",
            catch_response=True,
        ) as r:
            if r.status_code in (200, 404):
                r.success()
            else:
                r.failure(f"status {r.status_code}")

    @tag("static")
    @task(3)
    def spa_share_page(self):
        """공유 링크 페이지 — SPA 라우트 (index.html로 fallback, on_start에서 자동 발급받은 공유 링크 사용)"""
        token = getattr(self, "share_token", None) or "test-token-abc"
        with self.client.get(
            f"/share/{token}",
            name="GET /share/{token}",
            catch_response=True,
        ) as r:
            self._check_status(r)

    # ──────────────────────────────────────────
    # Health / 공개 (인증 불필요) - Nginx를 통해 /api 경로로 접근
    # ──────────────────────────────────────────

    def _check_status(self, r, name_prefix=""):
        """4xx/5xx를 실패로 기록해 예외 메시지 길이를 줄임."""
        if 200 <= r.status_code < 300:
            r.success()
        else:
            r.failure(f"status {r.status_code}")

    @tag("health", "api")
    @task(4)
    def health_check(self):
        """Health check — 로드밸런서/모니터링용"""
        with self.client.get(
            "/api/health/",
            name="GET /api/health/",
            catch_response=True,
        ) as r:
            self._check_status(r)

    @tag("health", "api")
    @task(1)
    def health_liveness(self):
        with self.client.get(
            "/api/health/liveness",
            name="GET /api/health/liveness",
            catch_response=True,
        ) as r:
            self._check_status(r)

    @tag("health", "api")
    @task(1)
    def health_readiness(self):
        with self.client.get(
            "/api/health/readiness",
            name="GET /api/health/readiness",
            catch_response=True,
        ) as r:
            self._check_status(r)

    @tag("health", "api")
    @task(1)
    def health_detailed(self):
        with self.client.get(
            "/api/health/detailed",
            name="GET /api/health/detailed",
            catch_response=True,
        ) as r:
            self._check_status(r)

    @tag("api")
    @task(1)
    def api_root(self):
        """API 정보"""
        with self.client.get(
            "/api/",
            name="GET /api/",
            catch_response=True,
        ) as r:
            self._check_status(r)

    # ──────────────────────────────────────────
    # 인증 (Bearer 필요) - Nginx를 통해 /api 경로로 접근
    # ──────────────────────────────────────────

    @tag("auth", "api")
    @task(3)
    def auth_me(self):
        """현재 유저 프로필"""
        with self.client.get(
            "/api/auth/me",
            headers=get_auth_headers(self),
            name="GET /api/auth/me",
            catch_response=True,
        ) as r:
            self._check_status(r)

    # ──────────────────────────────────────────
    # Photos API - Nginx를 통해 /api 경로로 접근
    # ──────────────────────────────────────────

    @tag("photos", "api")
    @task(6)
    def photos_list(self):
        """사진 목록 (페이지네이션)"""
        with self.client.get(
            "/api/photos/?skip=0&limit=20",
            headers=get_auth_headers(self),
            name="GET /api/photos/",
            catch_response=True,
        ) as r:
            self._check_status(r)

    @tag("photos", "api")
    @task(3)
    def photo_detail(self):
        """사진 상세 (id=1 기준, 없으면 404)"""
        with self.client.get(
            "/api/photos/1",
            headers=get_auth_headers(self),
            name="GET /api/photos/{photo_id}",
            catch_response=True,
        ) as r:
            # 404는 해당 유저에 사진 없음으로 성공 처리
            if r.status_code in (200, 404):
                r.success()
            else:
                r.failure(f"status {r.status_code}")

    @tag("photos", "api")
    @task(2)
    def photo_image(self):
        """사진 이미지 접근 (JWT 필요, CDN 리다이렉트 가능)"""
        with self.client.get(
            "/api/photos/1/image",
            headers=get_auth_headers(self),
            name="GET /api/photos/{photo_id}/image",
            catch_response=True,
        ) as r:
            if r.status_code in (200, 404):
                r.success()
            else:
                r.failure(f"status {r.status_code}")

    @tag("photos", "api", "download")
    @task(2)
    def photo_download(self):
        """내 사진 목록 조회 후 하나 골라 이미지 다운로드 (실제 사용자 시나리오)"""
        with self.client.get(
            "/api/photos/?skip=0&limit=50",
            headers=get_auth_headers(self),
            name="GET /api/photos/ (list for download)",
            catch_response=True,
        ) as r:
            if r.status_code != 200:
                r.failure(f"status {r.status_code}")
                return
            if not r.content:
                r.failure("empty response")
                return
            try:
                photos = r.json()
            except Exception as e:
                r.failure(f"invalid JSON: {e}")
                return
            if not isinstance(photos, list):
                photos = getattr(photos, "photos", None) or getattr(photos, "items", None) or []
            if not isinstance(photos, list):
                r.failure("response is not a list")
                return
            r.success()
        if not photos:
            return
        one = random.choice(photos)
        photo_id = one.get("id") if isinstance(one, dict) else getattr(one, "id", None)
        if photo_id is None:
            return
        with self.client.get(
            f"/api/photos/{photo_id}/image",
            headers=get_auth_headers(self),
            name="GET /api/photos/{photo_id}/image (download)",
            catch_response=True,
        ) as img_r:
            if img_r.status_code != 200:
                img_r.failure(f"status {img_r.status_code}")
            else:
                img_r.success()

    # ──────────────────────────────────────────
    # Albums API - Nginx를 통해 /api 경로로 접근
    # ──────────────────────────────────────────

    @tag("albums", "api")
    @task(6)
    def albums_list(self):
        """앨범 목록"""
        with self.client.get(
            "/api/albums/?skip=0&limit=20",
            headers=get_auth_headers(self),
            name="GET /api/albums/",
            catch_response=True,
        ) as r:
            self._check_status(r)

    @tag("albums", "api")
    @task(3)
    def album_detail(self):
        """앨범 상세"""
        with self.client.get(
            "/api/albums/1",
            headers=get_auth_headers(self),
            name="GET /api/albums/{album_id}",
            catch_response=True,
        ) as r:
            if r.status_code in (200, 404):
                r.success()
            else:
                r.failure(f"status {r.status_code}")

    # ──────────────────────────────────────────
    # Shared Albums API - Nginx를 통해 /api 경로로 접근 (인증 불필요)
    # ──────────────────────────────────────────

    @tag("shared", "api")
    @task(2)
    def shared_album(self):
        """공유 앨범 접근 (인증 불필요, on_start에서 자동 발급받은 공유 링크 사용)"""
        token = getattr(self, "share_token", None)
        if not token:
            return  # 공유 링크가 없으면 스킵
        with self.client.get(
            f"/api/share/{token}",
            name="GET /api/share/{token}",
            catch_response=True,
        ) as r:
            if r.status_code in (200, 404):
                r.success()
            else:
                r.failure(f"status {r.status_code}")

    @tag("shared", "api")
    @task(1)
    def shared_album_image(self):
        """공유 앨범 이미지 (인증 불필요, on_start에서 자동 발급받은 공유 링크 사용)"""
        token = getattr(self, "share_token", None)
        if not token:
            return  # 공유 링크가 없으면 스킵
        # 공유 앨범에서 사진 목록을 가져와서 하나 선택
        with self.client.get(
            f"/api/share/{token}",
            name="GET /api/share/{token} (for image)",
            catch_response=True,
        ) as r:
            if r.status_code != 200:
                r.failure(f"status {r.status_code}")
                return
            try:
                data = r.json()
                photos = data.get("photos", []) if isinstance(data, dict) else []
                if not photos:
                    r.success()
                    return
                photo = random.choice(photos)
                photo_id = photo.get("id") if isinstance(photo, dict) else getattr(photo, "id", None)
                if photo_id is None:
                    r.success()
                    return
            except Exception:
                r.success()
                return
            r.success()
        
        # 선택한 사진의 이미지 다운로드
        with self.client.get(
            f"/api/share/{token}/photos/{photo_id}/image",
            name="GET /api/share/{token}/photos/{photo_id}/image",
            catch_response=True,
        ) as img_r:
            if img_r.status_code in (200, 404):
                img_r.success()
            else:
                img_r.failure(f"status {img_r.status_code}")

    # ─── 맞지 않는 트래픽 (부정/잘못된 요청, 4xx 기대) ───
    @tag("invalid", "api")
    @task(2)
    def invalid_share_token(self):
        """유효하지 않은 공유 토큰 (404/400 기대)"""
        token = random.choice(["invalid-token-xyz", "expired-link", "00000000", "bad"])
        with self.client.get(
            f"/api/share/{token}",
            name="GET /api/share/{token} [invalid]",
            catch_response=True,
        ) as r:
            if r.status_code in (404, 400, 410):
                r.success()
            else:
                r.failure(f"status {r.status_code}")

    @tag("invalid", "api")
    @task(2)
    def invalid_auth_token(self):
        """잘못된 JWT로 API 호출 (401 기대)"""
        with self.client.get(
            "/api/albums/?skip=0&limit=5",
            headers={"Authorization": "Bearer invalid.jwt.token"},
            name="GET /api/albums/ [invalid token]",
            catch_response=True,
        ) as r:
            if r.status_code == 401:
                r.success()
            else:
                r.failure(f"status {r.status_code}")

    @tag("invalid", "api")
    @task(1)
    def invalid_login(self):
        """틀린 계정으로 로그인 (401/400 기대)"""
        with self.client.post(
            "/api/auth/login",
            json={"email": "wrong@example.com", "password": "wrongpass"},
            name="POST /api/auth/login [invalid]",
            catch_response=True,
        ) as r:
            if r.status_code in (401, 400, 404):
                r.success()
            else:
                r.failure(f"status {r.status_code}")

    @tag("invalid", "api")
    @task(1)
    def invalid_api_path(self):
        """존재하지 않는 API 경로 (404 기대)"""
        with self.client.get(
            "/api/nonexistent-path-12345",
            name="GET /api/nonexistent [invalid path]",
            catch_response=True,
        ) as r:
            if r.status_code == 404:
                r.success()
            else:
                r.failure(f"status {r.status_code}")

    @tag("invalid", "api")
    @task(1)
    def invalid_photo_id(self):
        """없을 수 있는 photo_id 조회 (404 허용)"""
        with self.client.get(
            "/api/photos/999999999",
            headers=get_auth_headers(self),
            name="GET /api/photos/{id} [invalid id]",
            catch_response=True,
        ) as r:
            if r.status_code in (200, 404):
                r.success()
            else:
                r.failure(f"status {r.status_code}")

    # ──────────────────────────────────────────
    # 쓰기 (비중 낮춤 — 서버 상태 변경) - Nginx를 통해 /api 경로로 접근
    # ──────────────────────────────────────────

    @tag("albums", "write", "api")
    @task(1)
    def album_create(self):
        """앨범 생성"""
        with self.client.post(
            "/api/albums/",
            headers=get_auth_headers(self),
            json={
                "name": "LoadTest Album",
                "description": "Created by locust",
            },
            name="POST /api/albums/",
            catch_response=True,
        ) as r:
            if r.status_code in [200, 201]:
                r.success()
            elif r.status_code == 401:
                r.failure("Unauthorized - token may be invalid")
            else:
                r.failure(f"Unexpected status code: {r.status_code}")

    @tag("albums", "write", "shared", "api")
    @task(1)
    def album_share_create(self):
        """앨범 공유 링크 생성 (내 앨범 목록에서 하나 골라 공유)"""
        with self.client.get(
            "/api/albums/?skip=0&limit=20",
            headers=get_auth_headers(self),
            name="GET /api/albums/ (for share)",
            catch_response=True,
        ) as r:
            if r.status_code != 200 or not r.content:
                r.failure(f"status {r.status_code}" if r.status_code != 200 else "empty")
                return
            try:
                albums = r.json()
            except Exception:
                r.failure("invalid JSON")
                return
            r.success()
        if not isinstance(albums, list) or not albums:
            return
        album = random.choice(albums)
        album_id = album.get("id") if isinstance(album, dict) else getattr(album, "id", None)
        if album_id is None:
            return
        with self.client.post(
            f"/api/albums/{album_id}/share",
            headers={**get_auth_headers(self), "Content-Type": "application/json"},
            json={},
            name="POST /api/albums/{id}/share",
            catch_response=True,
        ) as r:
            if r.status_code in [200, 201]:
                r.success()
            elif r.status_code == 401:
                r.failure("Unauthorized")
            elif r.status_code == 404:
                r.failure("Album not found")
            else:
                r.failure(f"status {r.status_code}")

    @tag("photos", "write", "api")
    @task(1)
    def photos_upload(self):
        """업로드 필수: presigned → PUT → confirm 항상 수행. 앨범은 on_start에서 생성한 업로드용 앨범에 연결."""
        self._photo_upload_real()

    def _photo_upload_real(self):
        """presigned → Object Storage PUT → confirm 까지 수행. 앨범 없으면 생성 후 연결."""
        if not self.token:
            return
        # 앨범 보장: 없으면 업로드용 앨범 생성
        if getattr(self, "upload_album_id", None) is None:
            self._ensure_upload_album()
        album_id = getattr(self, "upload_album_id", None) or int(os.environ.get("UPLOAD_ALBUM_ID", "1"))

        if IMAGE_LIST:
            file_path, content_type, file_size = random.choice(IMAGE_LIST)
            filename = os.path.basename(file_path)
            try:
                with open(file_path, "rb") as f:
                    body = f.read()
            except OSError:
                return
        else:
            filename = "loadtest.jpg"
            content_type = "image/jpeg"
            body = MINIMAL_JPEG
            file_size = len(body)

        # 1) Presigned URL 발급
        with self.client.post(
            "/api/photos/presigned-url",
            headers=get_auth_headers(self),
            json={
                "album_id": album_id,
                "filename": filename,
                "content_type": content_type,
                "file_size": file_size,
            },
            name="POST /api/photos/presigned-url",
            catch_response=True,
        ) as r:
            if r.status_code not in [200, 201]:
                if r.status_code == 401:
                    r.failure("Unauthorized - token may be invalid")
                elif r.status_code == 404:
                    r.failure("Album not found")
                else:
                    r.failure(f"Unexpected status code: {r.status_code}")
                return
            try:
                data = r.json()
            except Exception as e:
                r.failure(str(e))
                return
            r.success()

        upload_url = data.get("upload_url")
        upload_headers = data.get("upload_headers") or {}
        photo_id = data.get("photo_id")
        if not upload_url or photo_id is None:
            return

        # 2) Object Storage에 PUT
        start = time.perf_counter()
        start_ts = time.time()
        from locust import events
        try:
            put_res = requests.put(
                upload_url,
                headers=upload_headers,
                data=body,
                timeout=60,
            )
            response_time_ms = (time.perf_counter() - start) * 1000
            if 200 <= put_res.status_code < 300:
                events.request.fire(
                    request_type="PUT",
                    name="PUT (Object Storage) upload",
                    start_time=start_ts,
                    response_time=response_time_ms,
                    response_length=0,
                    response=None,
                    context={},
                    exception=None,
                )
            else:
                events.request.fire(
                    request_type="PUT",
                    name="PUT (Object Storage) upload",
                    start_time=start_ts,
                    response_time=response_time_ms,
                    response_length=0,
                    response=None,
                    context={},
                    exception=Exception(f"PUT {put_res.status_code}"),
                )
        except Exception as e:
            response_time_ms = (time.perf_counter() - start) * 1000
            events.request.fire(
                request_type="PUT",
                name="PUT (Object Storage) upload",
                start_time=start_ts,
                response_time=response_time_ms,
                response_length=0,
                response=None,
                context={},
                exception=e,
            )
            return

        # 3) 업로드 완료 확인
        with self.client.post(
            "/api/photos/confirm",
            headers={**get_auth_headers(self), "Content-Type": "application/json"},
            json={"photo_id": photo_id},
            name="POST /api/photos/confirm",
            catch_response=True,
        ) as c:
            if c.status_code in [200, 201]:
                c.success()
            elif c.status_code == 401:
                c.failure("Unauthorized")
            else:
                c.failure(f"Unexpected status code: {c.status_code}")


# ──────────────────────────────────────────────────
# (선택) StepLoadShape — 단계별 부하
# ──────────────────────────────────────────────────

from locust import LoadTestShape


class StepLoadShape(LoadTestShape):
    """
    자동 단계별 부하 증가
    
    5분씩 유지하며 Users를 올림:
      0-5분:   100 Users
      5-10분:  200 Users
      10-15분: 500 Users
      15-20분: 1000 Users
      20-25분: 2000 Users
      25-30분: 3000 Users

    사용법:
      python3 -m locust -f locustfile_integrated.py --headless \
        --host http://<nginx-host> --csv=integrated_step
      
    멈추는 기준:
      - P95 > 300ms (Nginx 프록시 + Backend 응답 시간)
      - 에러율(404 제외) > 1%
      - CPU > 85%
      - Connection Pool Waiting > 10
    """
    stages = [
        {"duration": 300,  "users": 100,  "spawn_rate": 20},   # 0-5분
        {"duration": 600,  "users": 200,  "spawn_rate": 40},   # 5-10분{"duration": 600,  "users": 200,  "spawn_rate": 40}, 
        {"duration": 900,  "users": 400,  "spawn_rate": 40}, 
        {"duration": 900,  "users": 800,  "spawn_rate": 40}, 
    ]

    def tick(self):
        run_time = self.get_run_time()
        for stage in self.stages:
            if run_time < stage["duration"]:
                return (stage["users"], stage["spawn_rate"])
        return None
