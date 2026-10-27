"""Run in the user's terminal. Never print or pass the key in shell arguments."""
import getpass
import argparse
import os
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / 'work/credentials/openrouter.key'

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replace', action='store_true', help='Replace a previously saved key using hidden terminal input')
    args = parser.parse_args()
    if not os.isatty(0):
        raise SystemExit('실제 터미널에서 실행하세요. 키를 명령어나 채팅에 넣지 마세요.')
    if DEST.exists() and not args.replace:
        raise SystemExit('키 파일이 이미 있습니다. 교체하려면 --replace 옵션을 사용하세요.')
    if DEST.is_symlink():
        raise SystemExit('키 경로가 심볼릭 링크입니다. 저장하지 않았습니다.')
    key = getpass.getpass('OpenRouter API 키 붙여넣기 (화면에 표시되지 않음): ').strip()
    if not key.startswith('sk-or-') or any(c.isspace() for c in key):
        raise SystemExit('OpenRouter 키 형식을 확인하세요. 저장하지 않았습니다.')
    DEST.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    DEST.parent.chmod(0o700)
    if args.replace:
        fd, temporary = tempfile.mkstemp(prefix='.openrouter-', dir=DEST.parent)
        try:
            with os.fdopen(fd, 'w') as f:
                f.write(key + '\n')
            os.replace(temporary, DEST)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)
    else:
        fd = os.open(DEST, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(key + '\n')
    print('키 저장 완료. API 호출이나 과금은 하지 않았습니다.')

if __name__ == '__main__':
    main()
