"""Decode the reader font using its character map."""
import json
from pathlib import Path
import re
from app.providers import ProviderError


FONT_ID = 'dc027189e0ba4cd'
TABLE = Path(__file__).with_name('data')/'fanqie-font-dc027189e0ba4cd.json'


def decode(text, html):
    private = {c for c in text if '\ue000' <= c <= '\uf8ff'}
    if not private:
        return text
    fonts = set(re.findall(r'awesome-font/c/([a-z0-9]+)(?:-\d+)?\.woff2?', html))
    if fonts != {FONT_ID}:
        raise ProviderError('番茄阅读字体已变化，当前映射不适用，未保存乱码正文')
    mapping = json.loads(TABLE.read_text(encoding='utf-8'))['characters']
    if any(str(ord(c)) not in mapping for c in private):
        raise ProviderError('番茄正文包含尚未验证的字体字符，未保存乱码正文')
    return text.translate({int(code): char for code, char in mapping.items()})
