"""
시나리오 공통 베이스 — 로그인/로그아웃, 앨범 추가·삭제, 이미지 업로드, 공유 링크 생성·접속·삭제, 타당하지 않은 접속 포함.
다운로드 기능은 제외 (삭제됨).
"""

import os
import random
import sys
import time
from pathlib import Path

import requests
from locust import HttpUser, task, between, tag

# 프로젝트 루트 + integrated-test
_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_root))
try:
    from common.image_upload_helper import load_image_list
    from common.user_list_helper import load_user_list
except ImportError:
    def load_image_list():
        return []
    def load_user_list():
        return []

IMAGE_LIST = load_image_list()
USER_LIST = load_user_list()
_user_index = [0]


def get_auth_headers(user) -> dict:
    if getattr(user, "token", None):
        return {"Authorization": f"Bearer {user.token}"}
    return {}


class ScenarioBaseUser(HttpUser):
    """시나리오 공통 유저: 로그인/로그아웃, 앨범 CRUD, 공유 CRUD, 이미지 업로드, 부정 접근. 다운로드 없음."""
    wait_time = between(0.5, 1.5)

    def on_start(self):
        self.token = os.environ.get("LOADTEST_TOKEN")
        self.share_token = None
        self.share_id = None
        self.share_album_id = None

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

            if not self.token and not USER_LIST:
                with self.client.post(
                    "/api/auth/register",
                    json={"email": email, "username": username, "password": password},
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
                        ) as lr:
                            if lr.status_code == 200:
                                try:
                                    self.token = lr.json().get("access_token")
                                    lr.success()
                                except Exception:
                                    self.token = None
                                    lr.failure("invalid login response")
                            else:
                                lr.failure(f"status {lr.status_code}")
                    else:
                        r.failure(f"status {r.status_code}")

        if self.token:
            self._ensure_share_token()

    def _ensure_share_token(self):
        with self.client.post(
            "/api/albums/",
            headers=get_auth_headers(self),
            json={"name": "LoadTest Share Album", "description": "For shared link test"},
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
                self.share_token = data.get("token") if isinstance(data, dict) else getattr(data, "token", None)
                self.share_id = data.get("id") if isinstance(data, dict) else getattr(data, "id", None)
                self.share_album_id = data.get("album_id") if isinstance(data, dict) else getattr(data, "album_id", album_id)
            except Exception:
                pass

    def _check_status(self, r, name_prefix=""):
        if 200 <= r.status_code < 300:
            r.success()
        else:
            r.failure(f"status {r.status_code}")

    # ─── 로그인 / 로그아웃 시뮬레이션 ───
    @tag("auth")
    @task(2)
    def auth_me(self):
        with self.client.get(
            "/api/auth/me",
            headers=get_auth_headers(self),
            name="GET /api/auth/me",
            catch_response=True,
        ) as r:
            self._check_status(r)

    @tag("auth", "logout")
    @task(1)
    def login_then_continue(self):
        """로그아웃 시뮬레이션: 잘못된 비밀번호로 로그인 시도 후 기존 토큰으로 다시 사용 (실제 로그아웃 API 없음)."""
        with self.client.post(
            "/api/auth/login",
            json={"email": "wrong@example.com", "password": "wrongpass"},
            name="POST /api/auth/login (invalid - expect 401)",
            catch_response=True,
        ) as r:
            if r.status_code in (401, 400, 404):
                r.success()
            else:
                r.failure(f"status {r.status_code}")

    # ─── 앨범 추가·삭제 ───
    @tag("albums", "api")
    @task(4)
    def albums_list(self):
        with self.client.get(
            "/api/albums/?skip=0&limit=20",
            headers=get_auth_headers(self),
            name="GET /api/albums/",
            catch_response=True,
        ) as r:
            self._check_status(r)

    @tag("albums", "write", "api")
    @task(2)
    def album_create(self):
        with self.client.post(
            "/api/albums/",
            headers=get_auth_headers(self),
            json={"name": "LoadTest Album", "description": "Created by locust"},
            name="POST /api/albums/",
            catch_response=True,
        ) as r:
            if r.status_code in [200, 201]:
                r.success()
            elif r.status_code == 401:
                r.failure("Unauthorized")
            else:
                r.failure(f"status {r.status_code}")

    @tag("albums", "write", "api")
    @task(1)
    def album_delete(self):
        """앨범 목록에서 하나 골라 삭제 (본인 소유, on_start에서 만든 앨범 제외 권장을 위해 목록에서 선택)."""
        with self.client.get(
            "/api/albums/?skip=0&limit=50",
            headers=get_auth_headers(self),
            name="GET /api/albums/ (for delete)",
            catch_response=True,
        ) as r:
            if r.status_code != 200 or not r.content:
                if r.status_code != 200:
                    r.failure(f"status {r.status_code}")
                return
            try:
                albums = r.json()
            except Exception:
                r.failure("invalid JSON")
                return
            r.success()
        if not isinstance(albums, list) or len(albums) < 2:
            return
        album = random.choice([a for a in albums if a.get("id") != self.share_album_id][:10] or albums)
        album_id = album.get("id") if isinstance(album, dict) else getattr(album, "id", None)
        if album_id is None:
            return
        with self.client.delete(
            f"/api/albums/{album_id}",
            headers=get_auth_headers(self),
            name="DELETE /api/albums/{id}",
            catch_response=True,
        ) as r:
            if r.status_code in (200, 204):
                r.success()
            elif r.status_code in (401, 404):
                r.failure(f"status {r.status_code}")
            else:
                r.failure(f"status {r.status_code}")

    # ─── 이미지 업로드 ───
    @tag("photos", "write", "api")
    @task(2)
    def photos_upload(self):
        if IMAGE_LIST:
            self._photo_upload_real()
        else:
            self._photos_presigned_url_only()

    def _photos_presigned_url_only(self):
        with self.client.post(
            "/api/photos/presigned-url",
            headers=get_auth_headers(self),
            json={"album_id": 1, "filename": "loadtest.jpg", "content_type": "image/jpeg", "file_size": 1024},
            name="POST /api/photos/presigned-url",
            catch_response=True,
        ) as r:
            if r.status_code in [200, 201]:
                r.success()
            elif r.status_code in (401, 404):
                r.failure(f"status {r.status_code}")
            else:
                r.failure(f"status {r.status_code}")

    def _photo_upload_real(self):
        file_path, content_type, file_size = random.choice(IMAGE_LIST)
        filename = os.path.basename(file_path)
        album_id = int(os.environ.get("UPLOAD_ALBUM_ID", "1"))
        with self.client.post(
            "/api/photos/presigned-url",
            headers=get_auth_headers(self),
            json={"album_id": album_id, "filename": filename, "content_type": content_type, "file_size": file_size},
            name="POST /api/photos/presigned-url",
            catch_response=True,
        ) as r:
            if r.status_code not in [200, 201]:
                if r.status_code == 401:
                    r.failure("Unauthorized")
                elif r.status_code == 404:
                    r.failure("Album not found")
                else:
                    r.failure(f"status {r.status_code}")
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
        try:
            with open(file_path, "rb") as f:
                body = f.read()
        except OSError:
            return
        start = time.perf_counter()
        start_ts = time.time()
        from locust import events
        try:
            put_res = requests.put(upload_url, headers=upload_headers, data=body, timeout=60)
            rt = (time.perf_counter() - start) * 1000
            ok = 200 <= put_res.status_code < 300
            events.request.fire(
                request_type="PUT", name="PUT (Object Storage) upload",
                start_time=start_ts, response_time=rt, response_length=0, response=None, context={},
                exception=None if ok else Exception(f"PUT {put_res.status_code}"),
            )
        except Exception as e:
            rt = (time.perf_counter() - start) * 1000
            events.request.fire(
                request_type="PUT", name="PUT (Object Storage) upload",
                start_time=start_ts, response_time=rt, response_length=0, response=None, context={}, exception=e,
            )
            return
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
                c.failure(f"status {c.status_code}")

    # ─── 공유 링크 생성·접속·삭제 ───
    @tag("shared", "api")
    @task(3)
    def shared_album(self):
        token = getattr(self, "share_token", None) or "test-token"
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
        token = getattr(self, "share_token", None) or "test-token"
        with self.client.get(
            f"/api/share/{token}/photos/1/image",
            name="GET /api/share/{token}/photos/{photo_id}/image",
            catch_response=True,
        ) as r:
            if r.status_code in (200, 404):
                r.success()
            else:
                r.failure(f"status {r.status_code}")

    @tag("albums", "write", "shared", "api")
    @task(1)
    def album_share_create(self):
        with self.client.get(
            "/api/albums/?skip=0&limit=20",
            headers=get_auth_headers(self),
            name="GET /api/albums/ (for share)",
            catch_response=True,
        ) as r:
            if r.status_code != 200 or not r.content:
                if r.status_code != 200:
                    r.failure(f"status {r.status_code}")
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
            elif r.status_code in (401, 404):
                r.failure(f"status {r.status_code}")
            else:
                r.failure(f"status {r.status_code}")

    @tag("albums", "write", "shared", "api")
    @task(1)
    def share_link_delete(self):
        """공유 링크 삭제: 앨범별 공유 목록 조회 후 하나 삭제."""
        if not self.token:
            return
        with self.client.get(
            "/api/albums/?skip=0&limit=20",
            headers=get_auth_headers(self),
            name="GET /api/albums/ (for share delete)",
            catch_response=True,
        ) as r:
            if r.status_code != 200 or not r.content:
                return
            try:
                albums = r.json()
            except Exception:
                return
        if not isinstance(albums, list) or not albums:
            return
        for album in random.sample(albums, min(len(albums), 5)):
            album_id = album.get("id") if isinstance(album, dict) else getattr(album, "id", None)
            if album_id is None:
                continue
            with self.client.get(
                f"/api/albums/{album_id}/share",
                headers=get_auth_headers(self),
                name="GET /api/albums/{id}/share",
                catch_response=True,
            ) as sr:
                if sr.status_code != 200 or not sr.content:
                    continue
                try:
                    links = sr.json()
                except Exception:
                    continue
            if not isinstance(links, list) or not links:
                continue
            link = random.choice(links)
            share_id = link.get("id") if isinstance(link, dict) else getattr(link, "id", None)
            if share_id is None:
                continue
            with self.client.delete(
                f"/api/albums/{album_id}/share/{share_id}",
                headers=get_auth_headers(self),
                name="DELETE /api/albums/{id}/share/{share_id}",
                catch_response=True,
            ) as dr:
                if dr.status_code in (200, 204):
                    dr.success()
                elif dr.status_code in (401, 404):
                    dr.failure(f"status {dr.status_code}")
                else:
                    dr.failure(f"status {dr.status_code}")
            return
        return

    # ─── 타당하지 않은 접속 (부정 접근) ───
    @tag("invalid", "api")
    @task(2)
    def invalid_share_token(self):
        """유효하지 않은 공유 토큰으로 접속 (404/400 기대)."""
        fake_tokens = ["invalid-token-xyz", "expired-link", "00000000", ""]
        token = random.choice(fake_tokens) or "empty"
        with self.client.get(
            f"/api/share/{token}",
            name="GET /api/share/{token} (invalid)",
            catch_response=True,
        ) as r:
            if r.status_code in (404, 400, 410):
                r.success()
            else:
                r.failure(f"status {r.status_code}")

    @tag("invalid", "api")
    @task(1)
    def invalid_auth_token(self):
        """잘못된 JWT로 인증 필요 API 호출 (401 기대)."""
        with self.client.get(
            "/api/albums/?skip=0&limit=5",
            headers={"Authorization": "Bearer invalid.jwt.token"},
            name="GET /api/albums/ (invalid token)",
            catch_response=True,
        ) as r:
            if r.status_code == 401:
                r.success()
            else:
                r.failure(f"status {r.status_code}")

    # ─── 읽기 전용 API (사설/개인) ───
    @tag("photos", "api")
    @task(3)
    def photos_list(self):
        with self.client.get(
            "/api/photos/?skip=0&limit=20",
            headers=get_auth_headers(self),
            name="GET /api/photos/",
            catch_response=True,
        ) as r:
            self._check_status(r)

    @tag("photos", "api")
    @task(1)
    def photo_detail(self):
        with self.client.get(
            "/api/photos/1",
            headers=get_auth_headers(self),
            name="GET /api/photos/{photo_id}",
            catch_response=True,
        ) as r:
            if r.status_code in (200, 404):
                r.success()
            else:
                r.failure(f"status {r.status_code}")

    @tag("photos", "api")
    @task(1)
    def photo_image(self):
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

    @tag("health", "api")
    @task(1)
    def health_check(self):
        with self.client.get("/api/health/", name="GET /api/health/", catch_response=True) as r:
            self._check_status(r)
