# Nginx 부하 테스트 도구 (Locust)

Python [Locust](https://locust.io/)를 사용한 Nginx 서버 부하/스트레스 테스트 도구입니다.

## 요구사항

- Python 3.8+
- pip

## 설치

```bash
pip install -r requirements.txt
```

## 사용법

> **실행 방법**: `locust` 명령이 없으면 `python3 -m locust` 로 실행하세요.
> ```bash
> python3 -m locust -f locustfile.py --host=http://대상주소:80
> ```

### 1. 웹 UI 모드 (권장)

대상 Nginx 호스트를 **하나만** 지정하고 Locust 웹 UI를 띄웁니다.

```bash
# 기본: http://localhost (포트 8089에서 UI)
python3 -m locust -f locustfile.py

# 대상 호스트 지정
python3 -m locust -f locustfile.py --host=http://localhost:80

# 다른 머신의 Nginx 테스트
python3 -m locust -f locustfile.py --host=http://192.168.1.100:80
```

브라우저에서 **http://localhost:8089** 로 접속한 뒤:

- **Number of users**: 동시 가상 사용자 수
- **Spawn rate**: 초당 생성할 사용자 수
- **Start** 로 테스트 시작

### 2. 헤드리스(CLI) 모드

UI 없이 터미널에서 바로 실행할 때:

```bash
# 10명 사용자, 10초 동안, 초당 2명씩 생성
python3 -m locust -f locustfile.py --host=http://localhost:80 \
  --headless -u 10 -r 2 -t 10s

# 100명 사용자, 1분 동안
python3 -m locust -f locustfile.py --host=http://your-nginx-server:80 \
  --headless -u 100 -r 10 -t 1m
```

### 3. 특정 User 클래스만 사용

`locustfile.py` 에는 두 가지 시나리오가 있습니다.

- **NginxLoadUser**: 일반 부하 (요청 간 1~3초 대기)
- **NginxStressUser**: 스트레스 (0.1~0.5초 대기, 빠른 연속 요청)

한 종류만 쓰려면:

```bash
python3 -m locust -f locustfile.py --host=http://localhost:80 NginxStressUser
```

## 옵션 요약

| 옵션 | 설명 |
|------|------|
| `-f locustfile.py` | 시나리오 파일 |
| `--host=URL` | 테스트 대상 Nginx base URL |
| `--headless` | 웹 UI 없이 실행 |
| `-u N` | 동시 사용자 수 |
| `-r N` | 초당 생성 사용자 수 (spawn rate) |
| `-t 30s` / `-t 2m` | 테스트 지속 시간 |
| `--web-port=8089` | 웹 UI 포트 (기본 8089) |

## 시나리오 설명

- **루트(/)**: 가장 자주 호출되는 요청
- **정적 리소스**: `/static/*`, `/favicon.ico` 등
- **헬스/상태**: `/health`, `/status` (해당 경로가 없으면 404로 기록됨)
- **쿼리 스트링**: `/?query`, `/api?page=1` 등

Nginx에 실제로 없는 경로(`/health`, `/status`, `/static/*` 등)는 404로 찍히므로, 필요하면 `locustfile.py` 안의 경로를 자신의 서버에 맞게 수정하면 됩니다.

## 결과 해석

- **RPS**: 초당 요청 수
- **Response Times**: 응답 시간 (평균, 중앙값, 95%/99% 백분위)
- **Failures**: 실패 비율 (타임아웃, 5xx 등)

일반적으로 평균/95% 응답 시간이 목표 SLA 이내인지, 실패율이 0%에 가까운지 확인하면 됩니다.
