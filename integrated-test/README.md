# 통합 부하 테스트

Load Balancer → Nginx → Load Balancer → Backend 구조의 통합 부하 테스트

## 대상 구성

- **Load Balancer** → **Nginx** → **Load Balancer** → **Backend**
- Nginx는 웹 서빙도 하지만 `/api` 엔드포인트를 통해 백엔드에 접속 가능
- SPA 정적 서빙: `/`, `/share/{token}`, JS/CSS/ICO
- 리버스 프록시: `/api/*` → photo_api_backend

## 테스트 범위

### 정적 파일 서빙 (Nginx 직접 처리)
- SPA index.html
- JS/CSS 번들 파일
- favicon
- 공유 링크 페이지

### API 프록시 (Nginx → Backend)
- Health check 엔드포인트
- 인증 (로그인, 프로필 조회)
- Photos API (목록, 상세, 이미지)
- Albums API (목록, 상세, 생성)
- Shared Albums API (공유 앨범 접근)

## 사용법

### 기본 실행 (대화형)

```bash
python3 -m locust -f locustfile_integrated.py --host http://<nginx-host>
```

### 헤드리스 모드

```bash
LOADTEST_EMAIL=user@example.com LOADTEST_PASSWORD=password123 \
  python3 -m locust -f locustfile_integrated.py --headless \
  -u 200 -r 40 --run-time 5m \
  --host http://<nginx-host> \
  --csv=integrated_result
```

### run_test.py 사용 (권장)

```bash
# StepLoadShape 사용 (자동 단계별 부하 증가)
python3 run_test.py --host http://<nginx-host>

# 수동으로 부하 설정
python3 run_test.py --host http://<nginx-host> -u 200 -r 40 --run-time 5m
```

### 환경변수

- `LOADTEST_TOKEN`: 미리 발급한 JWT 토큰 (로그인 생략)
- `LOADTEST_EMAIL`: 테스트 계정 이메일 (기본: loadtest@example.com)
- `LOADTEST_PASSWORD`: 테스트 계정 비밀번호 (기본: loadtest123)
- `LOADTEST_USERNAME`: 테스트 계정 사용자명 (기본: 이메일 앞부분)

**참고**: 각 가상 유저는 로그인 성공 시 자동으로 앨범을 생성하고 공유 링크를 발급받아 사용합니다.

### 실제 사용자처럼 이미지 업로드 테스트

이미지 **목록**을 주면, presigned URL 발급 → Object Storage PUT → confirm 까지 **실제 파일**로 수행합니다.  
(설정이 없으면 기존처럼 presigned URL만 발급하는 동작입니다.)

**이미지 목록 지정 (둘 중 하나)**

- **`UPLOAD_IMAGE_DIR`**: 이미지가 들어 있는 디렉터리 경로  
  - 해당 디렉터리 아래를 재귀 검색해 `.jpg`, `.jpeg`, `.png`, `.gif`, `.webp`, `.heic` 수집
- **`UPLOAD_IMAGE_LIST`**: 한 줄에 하나씩 파일 경로가 적힌 텍스트 파일 경로  
  - `#`으로 시작하는 줄은 무시, 상대 경로는 리스트 파일 기준으로 해석

**추가 환경변수**

- **`UPLOAD_ALBUM_ID`**: 업로드할 앨범 ID (기본: 1). 해당 앨범이 없으면 404 발생.

**실행 예시**

```bash
# 디렉터리 지정: ./sample_images/ 안의 이미지들로 업로드
UPLOAD_IMAGE_DIR=./sample_images \
  LOADTEST_EMAIL=user@example.com LOADTEST_PASSWORD=password123 \
  python3 -m locust -f locustfile_integrated.py --headless \
  -u 10 -r 2 --run-time 2m --host http://<nginx-host>

# 파일 목록 지정: 이미지 경로가 나열된 텍스트 파일
UPLOAD_IMAGE_LIST=./my_images.txt \
  python3 -m locust -f locustfile_integrated.py --headless \
  -u 5 -r 1 --run-time 1m --host http://<nginx-host>
```

`my_images.txt` 예시:

```
# 한 줄에 하나의 경로 (빈 줄, # 주석 가능)
/path/to/photo1.jpg
./relative/photo2.png
```

각 가상 유저는 목록에서 **랜덤으로 이미지를 골라** 업로드하므로, 실제 사용자 패턴에 가깝게 테스트할 수 있습니다.

### 아이디(이메일) 목록 + 이미지 폴더: 업로드·다운로드

**이메일 목록**과 **이미지 폴더**를 함께 주면, 가상 유저마다 서로 다른 계정으로 로그인한 뒤 **업로드**와 **다운로드**를 모두 수행합니다.

**계정 목록 (이메일·비밀번호)**

- **`UPLOAD_USER_LIST`**: 한 줄에 한 계정. 형식 `email` 또는 `email,password`
  - 비밀번호 생략 시 `LOADTEST_PASSWORD` 사용 (없으면 `loadtest123`)
  - `#` 주석, 빈 줄 무시

**동작 요약**

| 설정 | 동작 |
|------|------|
| `UPLOAD_USER_LIST` | 가상 유저가 목록에서 계정을 라운드로빈으로 할당받아 해당 계정으로 로그인 |
| `UPLOAD_IMAGE_DIR` / `UPLOAD_IMAGE_LIST` | 업로드 시 위 목록에서 랜덤 이미지로 presigned → PUT → confirm |
| (항상) | **다운로드** 태스크: 내 사진 목록 조회 → 하나 골라 `GET /api/photos/{id}/image` |

**실행 예시 (이메일 목록 + 이미지 폴더)**

```bash
# integrated-test 디렉터리에서 실행 (locustfile과 users.txt, sample_images 경로 기준)
cd integrated-test
UPLOAD_USER_LIST=./users.txt \
  UPLOAD_IMAGE_DIR=./sample_images \
  python3 -m locust -f locustfile_integrated.py --headless \
  -u 20 -r 4 --run-time 3m --host http://<nginx-host>
```

`users.txt` 예시:

```
# 한 줄에 email 또는 email,password
user1@example.com,secret1
user2@example.com,secret2
user3@example.com
# user3은 비밀번호 생략 → LOADTEST_PASSWORD 사용
```

- **계정 자동 등록**: 로그인 실패 시 자동으로 계정 등록을 시도합니다 (USER_LIST 사용 중이어도 동일)
- 등록 성공 후 자동으로 로그인하여 토큰을 발급받습니다
- 따라서 테스트 전에 미리 계정을 생성할 필요가 없습니다
- **공유 링크 자동 발급**: 각 가상 유저는 로그인 성공 시 자동으로 앨범을 생성하고 공유 링크를 발급받아 사용합니다
- 업로드할 앨범이 필요하면 `UPLOAD_ALBUM_ID`(기본 1)에 맞는 앨범을 각 계정에 준비하거나, 테스트 초반에 앨범 생성 태스크가 실행되도록 두면 됩니다

## 멈추는 기준

- P95 > 300ms (Nginx 프록시 + Backend 응답 시간)
- 에러율(404 제외) > 1%
- CPU > 85%
- Connection Pool Waiting > 10

## StepLoadShape 단계

자동 단계별 부하 증가:
- 0-5분:   100 Users
- 5-10분:  200 Users
- 10-15분: 500 Users
- 15-20분: 1000 Users
- 20-25분: 2000 Users
- 25-30분: 3000 Users

## 결과 저장

`run_test.py`를 사용하면 결과가 `results/YYYYMMDD_HHMMSS/` 폴더에 자동 저장됩니다:
- `integrated_result_stats.csv`: 통계 요약
- `integrated_result_stats_history.csv`: 시간별 통계
- `integrated_result_failures.csv`: 실패 요청
- `integrated_result_exceptions.csv`: 예외 발생
