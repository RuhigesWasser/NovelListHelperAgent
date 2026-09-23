"""Send an ephemeral ESJ login to the running local app, never through argv/files."""
import getpass
import json
from pathlib import Path
import urllib.error
import urllib.request


def main():
    root = Path(__file__).resolve().parents[1]
    state = root/'.local/server.json'
    if not state.exists():
        print('请先运行 Start.cmd 启动应用。')
        return 1
    server = json.loads(state.read_text(encoding='utf-8'))
    print('ESJ 临时登录：输入不会显示；账号、密码及 Cookie 不保存到文件。')
    email = getpass.getpass('账号: ')
    password = getpass.getpass('密码: ')
    try:
        request = urllib.request.Request(f'http://127.0.0.1:{server["port"]}/api/esj/session',
            data=json.dumps({'email':email,'password':password}).encode(),
            headers={'Content-Type':'application/json','X-Session-Token':server['token']})
        with urllib.request.urlopen(request,timeout=200) as response:
            result = json.load(response)
        print('已登录；会话仅保留到退出登录或应用停止。' if result['connected'] else '未登录')
        if result.get('access_notice'):
            print(result['access_notice'])
        return 0
    except urllib.error.HTTPError as exc:
        # The local endpoint supplies a sanitized error, never remote response HTML.
        try:
            message = json.load(exc).get('detail','登录失败')
        except (ValueError,UnicodeError):
            message = '登录失败'
        print(message)
        return 1
    except (urllib.error.URLError,TimeoutError):
        print('无法连接本地应用，请确认应用正在运行。')
        return 1
    finally:
        email = password = ''


if __name__ == '__main__':
    raise SystemExit(main())
