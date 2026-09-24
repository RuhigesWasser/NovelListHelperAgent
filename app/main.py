import argparse
import json
import os
import secrets
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from app.paths import ROOT, configure


def existing(local):
    try:
        data = json.loads((local/'server.json').read_text(encoding='utf-8'))
        port = int(data['port'])
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=1) as r:
            if json.load(r).get('app') == 'novel-list-helper':
                return f'http://127.0.0.1:{port}'
    except Exception:
        pass
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    local = configure()
    # Kernel lock is released on crash. The lock file itself contains no secret.
    lock = (local/'server.lock').open('a+b')
    lock.seek(0)
    lock.write(b'0')
    lock.flush()
    lock.seek(0)
    try:
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        url = existing(local)
        if url and not args.no_browser:
            webbrowser.open(url)
        lock.close()
        return 0 if url else 1
    import uvicorn
    from app.server import create_app
    token = secrets.token_hex(32)
    sock = socket.socket()
    try:
        sock.bind(('127.0.0.1', 8765))
    except OSError:
        sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(local, token, lambda: setattr(server, 'should_exit', True)),
        host='127.0.0.1', port=port, access_log=False, log_level='warning'))
    state = local/'server.json'
    def ready():
        while not server.started and not server.should_exit:
            time.sleep(0.1)
        if server.started:
            state.write_text(json.dumps({'port': port, 'token': token, 'pid': os.getpid()}), encoding='utf-8')
            if not args.no_browser:
                webbrowser.open(f'http://127.0.0.1:{port}')
    threading.Thread(target=ready, daemon=True).start()
    try:
        server.run(sockets=[sock])
    finally:
        if state.exists():
            try:
                if json.loads(state.read_text(encoding='utf-8')).get('token') == token:
                    state.unlink()
            except (OSError, ValueError):
                pass
        sock.close()
        lock.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
