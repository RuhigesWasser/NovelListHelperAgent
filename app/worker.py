"""A disposable worker: credentials arrive over stdin, never arguments or job files."""
import asyncio
import json
from pathlib import Path
import sys
from app.paths import configure, add_tools


def main():
    configure()
    add_tools()
    import ocr
    from fetch_thread import fetch_thread
    from common import extract_tid
    spec = json.load(sys.stdin)
    folder = Path(spec['folder'])
    secret = spec.get('key', '')
    try:
        from app.recovery import Recovery,recognize_images,write_json
        recovery=Recovery(folder,spec)
        if spec.get('resume') and (folder/'raw.json').exists():
            raw=json.loads((folder/'raw.json').read_text(encoding='utf8'))
        elif spec['kind'] == 'image':
            raw = {'floors': [{'text': '', 'images': [{'file': str(folder/'input.png')}]}]}
        else:
            images = folder/'images'
            images.mkdir(exist_ok=True)
            raw = asyncio.run(fetch_thread(extract_tid(spec['source']), str(images), 'origin', 30, True))
        write_json(folder/'raw.json',raw)
        engine = ocr.BuiltinOCR(spec.get('language', 'zh')) if spec['engine'] == 'builtin' else ocr.LlmOCR.from_config(spec)
        failures=recognize_images(raw,engine,folder,recovery)
        if failures:
            (folder/'error.txt').write_text(f'{failures} 张图片识别失败；其余图片已保存，可恢复失败项。',encoding='utf8')
            return 2
        (folder/'error.txt').unlink(missing_ok=True)
    except Exception as exc:
        message = str(exc).replace(secret, '[已隐藏]') if secret else str(exc)
        (folder/'error.txt').write_text(message[:2000], encoding='utf-8')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
