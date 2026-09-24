#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""可选本地 RapidOCR / Chat Completions 多模态 OCR；支持图片或抓取 JSON。"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import sys

from common import ensure_utf8_stdout
from llm_client import LlmOCR, PROMPT


def add_ocr_arguments(parser, default='none'):
    parser.add_argument('--ocr', choices=['none', 'builtin', 'llm'], default=default,
                        help='none 仅抓取；builtin 本地 OCR；llm 多模态 API')
    parser.add_argument('--language', choices=['zh', 'japan', 'korean'], default='zh',
                        help='内置 OCR 语言；日文/韩文需先在应用设置中确认安装模型')
    parser.add_argument('--llm-base-url', default=os.getenv('OCR_LLM_BASE_URL'),
                        help='兼容 API 基础地址（通常以 /v1 结尾），或完整 /chat/completions 地址')
    parser.add_argument('--llm-protocol', choices=['chat_completions','responses','anthropic','gemini','ollama'])
    parser.add_argument('--llm-endpoint-mode', choices=['auto','full'])
    parser.add_argument('--llm-stream', action='store_true', default=None, help='使用流式响应')
    parser.add_argument('--llm-no-stream', action='store_false', dest='llm_stream', default=None)
    parser.add_argument('--llm-auth', choices=['auto','bearer','x-api-key','api-key','x-goog-api-key','custom','query','none'])
    parser.add_argument('--llm-key-header', help='自定义密钥请求头/查询参数名称')
    parser.add_argument('--llm-token-field', choices=['max_tokens','max_completion_tokens'])
    parser.add_argument('--llm-model', default=os.getenv('OCR_LLM_MODEL'), help='支持图片输入的模型名')
    parser.add_argument('--llm-api-key-env', default='OCR_LLM_API_KEY', help='存放密钥的环境变量名')
    parser.add_argument('--llm-timeout', type=float, help='单次 API 请求超时秒数')
    parser.add_argument('--llm-max-tokens', type=int, help='输出 token 上限')


class BuiltinOCR:
    def __init__(self, language='zh'):
        try:
            from rapidocr_onnxruntime import RapidOCR
            from PIL import Image
        except ImportError as exc:
            raise RuntimeError('缺少内置 OCR 依赖，请用当前 Python 安装本技能 requirements-ocr.txt') from exc
        # 限制线程数，避免 CPU 推理过度争用；模型由安装包提供。
        options = {}
        if language != 'zh':
            from common import project_root
            root=Path(project_root(str(Path(__file__).resolve().parent)))
            sys.path[:0]=[str(root),str(root/'.agents/scripts')]
            from app.ocr_models import require
            options['rec_model_path'] = str(require(language))
        self.engine = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1, **options)

    def __call__(self, path):
        from PIL import Image, ImageOps
        lines = []
        self.last_layout=[]
        with Image.open(path) as source:
            im = ImageOps.exif_transpose(source).convert('RGB')
        # Very wide screenshots can lose isolated characters in the detector's
        # internal resize. Normalize width before splitting the long image.
        if im.width>1800:
            im=im.resize((1800,round(im.height*1800/im.width)),Image.Resampling.LANCZOS)
        # 长截图分段并保留重叠，按文字框中心归属去重，避免整张缩小后小字丢失。
        for start in range(0, im.height, 1400):
            top, bottom = max(0, start - 100), min(im.height, start + 1500)
            tile = im.crop((0, top, im.width, bottom))
            buffer = io.BytesIO()
            tile.save(buffer, format='PNG')
            result, _ = self.engine(buffer.getvalue())
            for box, text, score in result or []:
                center = sum(float(point[1]) for point in box) / len(box) + top
                if start <= center < min(im.height, start + 1400):
                    lines.append(text)
                    self.last_layout.append({'text':text,'box':[[float(x),float(y)+top] for x,y in box],'score':float(score)})
        return '\n'.join(lines)


def make_engine(args):
    if args.ocr == 'builtin':
        return BuiltinOCR(getattr(args, 'language', 'zh'))
    if args.ocr == 'llm':
        from common import project_root
        root=Path(project_root(str(Path(__file__).resolve().parent)))
        sys.path[:0]=[str(root),str(root/'.agents/scripts')]
        from app.llm_settings import LlmSettings
        saved = LlmSettings(root/'.local')
        mapping = {'base_url':'llm_base_url','model':'llm_model','timeout':'llm_timeout',
                   'max_tokens':'llm_max_tokens','protocol':'llm_protocol','endpoint_mode':'llm_endpoint_mode',
                   'stream':'llm_stream','auth':'llm_auth','key_header':'llm_key_header','token_field':'llm_token_field'}
        overrides = {key:getattr(args, attr) for key,attr in mapping.items() if getattr(args,attr,None) is not None}
        key = os.getenv(args.llm_api_key_env)
        if key is not None:
            overrides['key'] = key
        config = saved.draft(overrides)
        engine = LlmOCR.from_config(config)
        saved.ensure_vision(config, persist=False)
        return engine
    return None


def recognize_thread(data, engine, base_dir=None):
    """保持楼层/图片顺序；内容相同的图片只识别一次，失败时终止而不伪装成空文本。"""
    cache, output = {}, []
    for floor in data['floors']:
        texts = []
        for image in floor.get('images', []):
            path = Path(image['file'])
            if not path.is_absolute() and base_dir is not None:
                path = Path(base_dir) / path
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest not in cache:
                print(f'[OCR] {path.name}', file=sys.stderr)
                cache[digest] = engine(path)
            texts.append(cache[digest])
        output.append({'text': floor.get('text', ''), 'images': texts})
    return output


def write_json(data, out=None):
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if out:
        path = Path(out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + '\n', encoding='utf-8')
    print(text)


def main():
    ensure_utf8_stdout()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path, help='本地图片或 fetch_thread.py 生成的原始 JSON')
    parser.add_argument('--out', help='结果 JSON 输出路径')
    add_ocr_arguments(parser, default='builtin')
    args = parser.parse_args()
    if args.ocr == 'none':
        parser.error('ocr.py 请选择 builtin 或 llm；仅抓取请使用 fetch_thread.py')
    try:
        if args.out and args.input.resolve() == Path(args.out).resolve():
            raise ValueError('输入文件与 --out 不能是同一个文件')
        engine = make_engine(args)
        if args.input.suffix.lower() == '.json':
            data = json.loads(args.input.read_text(encoding='utf-8-sig'))
            result = recognize_thread(data, engine, args.input.resolve().parent)
        else:
            result = {'file': str(args.input.resolve()), 'text': engine(args.input)}
        write_json(result, args.out)
        return 0
    except Exception as exc:
        print(f'[失败] {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
