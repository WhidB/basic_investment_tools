"""Double-click launcher: keep dependencies in a project-local environment."""
from pathlib import Path
import subprocess
import sys
import venv


def main():
    root = Path(__file__).resolve().parent
    environment = root / ".venv"
    python = environment / "Scripts" / "python.exe"
    if not python.exists():
        print("최초 실행 준비 중입니다. 잠시 기다려 주세요.", flush=True)
        venv.EnvBuilder(with_pip=True).create(environment)
    check = subprocess.run(
        [str(python), "-c", "import yfinance; from zoneinfo import ZoneInfo; ZoneInfo('America/New_York')"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if check.returncode:
        print("필요한 패키지를 설치합니다. 최초 설치에는 인터넷 연결이 필요합니다.", flush=True)
        subprocess.run(
            [str(python), "-m", "pip", "install", "-r", str(root / "requirements.txt")],
            cwd=root, check=True,
        )
    if "--setup-only" in sys.argv:
        print("실행 준비 완료.")
        return 0
    return subprocess.run([str(python), str(root / "backtest.py")], cwd=root).returncode


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"실행 준비에 실패했습니다: {exc}")
        print("인터넷 연결과 폴더 쓰기 권한을 확인하고 run.bat을 다시 실행하세요.")
        raise SystemExit(1)
    except KeyboardInterrupt:
        print("\n실행을 취소했습니다.")
        raise SystemExit(1)
