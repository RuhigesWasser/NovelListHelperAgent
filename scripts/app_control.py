"""Local service control for the POSIX launcher (stdlib only)."""
import json
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parents[1]


def unlocked():
    path=ROOT/'.local/server.lock'
    if not path.exists():return True
    try:
        with path.open('r+b') as handle:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
                msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        return True
    except OSError:return False


def status():
    path=ROOT/'.local/server.json'
    if not path.exists():return None
    try:
        state=json.loads(path.read_text(encoding='utf-8'))
        port=int(state['port'])
        if not 1<=port<=65535:return None
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(f'http://127.0.0.1:{port}/health',timeout=2) as response:
            if json.load(response).get('app')=='novel-list-helper':return state
    except (OSError,ValueError,KeyError):pass
    return None


def main():
    mode=sys.argv[1]
    if mode=='status':
        current=status()
        if not current:return 1
        print(f'http://127.0.0.1:{current["port"]}')
        return 0
    if mode=='stop':
        current=status()
        if current:
            request=urllib.request.Request(f'http://127.0.0.1:{current["port"]}/api/shutdown',data=b'{}',
                headers={'X-Session-Token':current['token'],'Content-Type':'application/json'})
            urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request,timeout=5).close()
        deadline=time.monotonic()+90
        while not unlocked() and time.monotonic()<deadline:time.sleep(.25)
        if not unlocked():
            print('Application is still stopping; no data was removed.',file=sys.stderr);return 1
        print('Application stopped.')
        return 0
    raise ValueError('Unknown control mode')


if __name__=='__main__':
    raise SystemExit(main())
