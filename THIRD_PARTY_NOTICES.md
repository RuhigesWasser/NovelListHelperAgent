# 来源与第三方组件

拾页当前发行源码采用 MIT License，见 LICENSE。允许使用、修改、分发和商业使用，分发时保留版权与许可文本。

项目最初由 adk23333/NovelListHelperAgent 的技能与脚本工作方式发展而来：
https://github.com/adk23333/NovelListHelperAgent

当前 MIT 许可证仅适用于本项目发行源码，不对上述项目或其历史版本重新授权。

以下第三方组件仍适用其各自许可证，不因本项目采用 MIT 而改变。Windows 程序包预置的 Python 许可证位于 `vendor/python/LICENSE.txt`，uv 许可证位于 `vendor/uv/licenses/`；含桌面组件的包将 .NET 与 WebView2 SDK 的许可文本保存在 `vendor/licenses/`；其他依赖由包管理器安装：

| 组件 | 用途 | 官方来源 |
| --- | --- | --- |
| aiotieba | 贴吧接口 | https://github.com/Starry-OvO/aiotieba |
| RapidOCR / ONNX Runtime | 本地 OCR | https://github.com/RapidAI/RapidOCR / https://github.com/microsoft/onnxruntime |
| Pillow | 图像读取与转换 | https://github.com/python-pillow/Pillow |
| Beautiful Soup | HTML 解析 | https://www.crummy.com/software/BeautifulSoup/ |
| Pydantic、FastAPI、Uvicorn | 参数验证与本地服务 | https://github.com/pydantic/pydantic / https://github.com/fastapi/fastapi / https://github.com/encode/uvicorn |
| uv、Python | 私有运行环境 | https://github.com/astral-sh/uv / https://www.python.org/ |
| .NET、WebView2 | Windows 桌面窗口 | https://github.com/dotnet / https://learn.microsoft.com/microsoft-edge/webview2/ |

源码包不包含这些组件的二进制、OCR 模型或第三方网页正文。分发包含运行时或模型的二进制包时，还须随相应组件保留其许可证、NOTICE 和再分发说明。MIT 授权不涵盖用户导入的截图、小说封面、简介、正文、网站商标或服务访问权限。
