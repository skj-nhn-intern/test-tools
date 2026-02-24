#!/usr/bin/env python3
"""
통합 부하 테스트 실행 스크립트
결과를 타임스탬프 기반 폴더에 저장합니다.
"""

import os
import sys
import subprocess
from datetime import datetime
from pathlib import Path

def create_results_dir():
    """타임스탬프 기반 결과 폴더 생성"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_dir = Path("results") / timestamp
    results_dir.mkdir(parents=True, exist_ok=True)
    return results_dir

def main():
    """메인 함수"""
    # 결과 폴더 생성
    results_dir = create_results_dir()
    csv_prefix = str(results_dir / "integrated_result")
    
    print(f"📁 결과 저장 경로: {results_dir}/")
    print(f"📊 CSV 파일 접두사: {csv_prefix}")
    print()
    
    # Locust 명령어 구성
    locust_cmd = [
        "python3", "-m", "locust",
        "-f", "locustfile_integrated.py",
        "--headless",
    ]
    
    # 사용자 인자 파싱
    args = sys.argv[1:]
    
    # --host는 필수
    if "--host" not in args:
        print("❌ 오류: --host 옵션이 필요합니다.")
        print("사용법: python3 run_test.py --host http://<nginx-host> [기타 옵션]")
        print()
        print("예시:")
        print("  python3 run_test.py --host http://nginx.example.com -u 200 -r 40 --run-time 5m")
        print("  python3 run_test.py --host http://nginx.example.com  # StepLoadShape 사용")
        sys.exit(1)
    
    # CSV 옵션 처리 (기존 --csv가 있으면 덮어씀)
    if "--csv" in args:
        csv_idx = args.index("--csv")
        if csv_idx + 1 < len(args):
            args[csv_idx + 1] = csv_prefix
        else:
            args.append(csv_prefix)
    else:
        args.extend(["--csv", csv_prefix])
    
    # 환경변수 확인
    if not os.environ.get("LOADTEST_TOKEN") and not os.environ.get("LOADTEST_EMAIL"):
        print("⚠️  경고: LOADTEST_TOKEN 또는 LOADTEST_EMAIL 환경변수가 설정되지 않았습니다.")
        print("   기본 테스트 계정을 사용합니다.")
        print()
    
    # 나머지 인자 추가
    locust_cmd.extend(args)
    
    # Locust 실행
    print("🚀 테스트 시작...")
    print(f"명령어: {' '.join(locust_cmd)}")
    print()
    
    try:
        result = subprocess.run(locust_cmd, check=False)
        if result.returncode == 0:
            print()
            print(f"✅ 테스트 완료! 결과는 {results_dir}/ 폴더에 저장되었습니다.")
        else:
            print()
            print(f"⚠️  테스트가 종료되었습니다 (종료 코드: {result.returncode})")
            print(f"   결과는 {results_dir}/ 폴더에 저장되었습니다.")
        sys.exit(result.returncode)
    except KeyboardInterrupt:
        print()
        print("⚠️  테스트가 중단되었습니다.")
        print(f"   부분 결과는 {results_dir}/ 폴더에 저장되었습니다.")
        sys.exit(130)

if __name__ == "__main__":
    main()
