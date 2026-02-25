# 부하 테스트 시나리오 (시나리오 폴더)

실제 데이터를 사용해 동작하는 부하 테스트 시나리오입니다.  
**다운로드 기능은 제외**되어 있습니다.

## 사전 준비 (실제 데이터)

### 1. 계정 목록

- **시나리오 1 (100명)**: `UPLOAD_USER_LIST=./scenarios/users_100.txt`
- **시나리오 2 (300명)**: `UPLOAD_USER_LIST=./scenarios/users_500.txt` (300명만 사용)
- **시나리오 3**: 위와 동일하거나 단일 계정(`LOADTEST_EMAIL`/`LOADTEST_PASSWORD`) 사용 가능

포함된 파일:
- `users_100.txt`: user1@loadtest.local ~ user100@loadtest.local (비밀번호: loadtest123)
- `users_500.txt`: user1@loadtest.local ~ user500@loadtest.local (비밀번호: loadtest123)

**실제 테스트 전**에 백엔드에 해당 계정들을 미리 가입시키거나, API가 자동 등록을 지원하면 시나리오 1/3은 단일 계정으로도 실행 가능합니다.  
시나리오 2(300명)는 300개 이상 계정 사전 등록을 권장합니다.

### 2. 이미지 업로드용 파일

실제 이미지 업로드를 쓰려면 다음 중 하나를 설정하세요.

- `UPLOAD_IMAGE_DIR=./sample_images` (integrated-test 기준 sample_images 디렉터리)
- `UPLOAD_IMAGE_LIST=./경로/이미지목록.txt`

설정하지 않으면 presigned URL 발급만 수행합니다.

---

## 시나리오 1: 전반적인 공유 테스트

- **동시 접속자**: 100명
- **내용**: 로그인/로그아웃, 앨범 추가·삭제, 이미지 업로드, 공유 링크 생성·접속·삭제, **타당하지 않은 접속 포함**
- **다운로드**: 제외

```bash
cd integrated-test

UPLOAD_USER_LIST=./scenarios/users_100.txt \
UPLOAD_IMAGE_DIR=./sample_images \
python3 -m locust -f scenarios/locustfile_scenario1_shared_general.py \
  --headless -u 100 -r 20 --run-time 5m \
  --host http://<nginx-host> \
  --csv=scenario1_result
```

대화형 실행:

```bash
cd integrated-test
UPLOAD_USER_LIST=./scenarios/users_100.txt \
  python3 -m locust -f scenarios/locustfile_scenario1_shared_general.py \
  --host http://<nginx-host>
```

---

## 시나리오 2: 사전 예약 300명 서비스 출시

- **동시 접속자**: 300명 (불규칙 요청, 동시 접속 유지)
- **내용**: 시나리오 1과 동일한 액션 세트, 대기 시간 0.2~4초로 불규칙 전송
- **다운로드**: 제외

```bash
cd integrated-test

UPLOAD_USER_LIST=./scenarios/users_500.txt \
UPLOAD_IMAGE_DIR=./sample_images \
python3 -m locust -f scenarios/locustfile_scenario2_launch_300.py \
  --headless \
  --host http://<nginx-host> \
  --csv=scenario2_result
```

- 0~60초: 0 → 300명까지 증가 (spawn_rate 5)
- 60초 이후: 300명 유지 (최대 약 1시간까지)

---

## 시나리오 3: 공유·사설(개인) 혼합 접속

- **동시 접속자**: 원하는 수만큼 (예: 100)
- **내용**: 공유 링크 접근 + 로그인 후 개인 앨범/사진 조회 혼합
- **다운로드**: 제외

```bash
cd integrated-test

UPLOAD_USER_LIST=./scenarios/users_100.txt \
UPLOAD_IMAGE_DIR=./sample_images \
python3 -m locust -f scenarios/locustfile_scenario3_mixed_shared_private.py \
  --headless -u 100 -r 20 --run-time 5m \
  --host http://<nginx-host> \
  --csv=scenario3_result
```

---

## 공통 환경 변수

| 변수 | 설명 |
|------|------|
| `UPLOAD_USER_LIST` | 계정 목록 파일 경로 (email,password 한 줄씩) |
| `UPLOAD_IMAGE_DIR` | 업로드에 쓸 이미지 디렉터리 |
| `UPLOAD_IMAGE_LIST` | 업로드에 쓸 이미지 경로 목록 파일 |
| `UPLOAD_ALBUM_ID` | 업로드 대상 앨범 ID (기본 1) |
| `LOADTEST_EMAIL` / `LOADTEST_PASSWORD` | 단일 계정 모드 (UPLOAD_USER_LIST 미설정 시) |
| `LOADTEST_TOKEN` | 미리 발급한 JWT (로그인 생략) |

---

## 시나리오에서 하는 일 (요약)

- **로그인**: `/api/auth/login` (on_start)
- **로그아웃 시뮬레이션**: 잘못된 비밀번호 로그인 시도 (401 기대)
- **앨범 추가**: `POST /api/albums/`
- **앨범 삭제**: `DELETE /api/albums/{id}`
- **이미지 업로드**: presigned URL → PUT → confirm (또는 presigned만)
- **공유 링크 생성**: `POST /api/albums/{id}/share`
- **공유 링크 접속**: `GET /api/share/{token}`, `GET /api/share/{token}/photos/{id}/image`
- **공유 링크 삭제**: `GET /api/albums/{id}/share` → `DELETE /api/albums/{id}/share/{share_id}`
- **타당하지 않은 접속**: 잘못된 공유 토큰, 잘못된 JWT로 API 호출 (404/401 기대)
- **다운로드**: 사용하지 않음 (제외됨)
