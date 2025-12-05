import io
import os
import sys
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, HttpUrl, conint, confloat
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from PIL import Image


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36"
)


class FilterSettings(BaseModel):
    allowed_domains: List[str] = ["mmbiz.qpic.cn"]
    min_area: conint(ge=1) = 300_000
    min_width: conint(ge=1) = 600
    min_height: conint(ge=1) = 400
    aspect_ratio_min: confloat(gt=0) = 0.6
    aspect_ratio_max: confloat(gt=0) = 1.8
    trim_leading: conint(ge=0) = 2
    trim_trailing: conint(ge=0) = 2


class ProcessRequest(BaseModel):
    url: HttpUrl
    filters: Optional[FilterSettings] = None


app = FastAPI(title="WeChat PPT to PDF")

# Allow local dev without CORS friction
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def extract_image_urls(html: str) -> List[str]:
    soup = BeautifulSoup(html, "lxml")
    urls: List[str] = []
    for img in soup.find_all("img"):
        src = img.get("data-src") or img.get("src")
        if src:
            urls.append(src)
    return urls


def domain_allowed(url: str, allowed_domains: List[str]) -> bool:
    netloc = urlparse(url).netloc
    return any(domain in netloc for domain in allowed_domains)


def apply_edge_trimming(urls: List[str], leading: int, trailing: int) -> List[str]:
    trimmed = urls[leading:] if leading else urls[:]
    if trailing:
        trimmed = trimmed[: len(trimmed) - trailing]
    return trimmed


async def fetch_html(client: httpx.AsyncClient, url: str) -> str:
    resp = await client.get(url, headers={"User-Agent": DEFAULT_USER_AGENT}, follow_redirects=True)
    resp.raise_for_status()
    return resp.text


async def download_image(client: httpx.AsyncClient, url: str, referer: str) -> bytes:
    resp = await client.get(
        url,
        headers={"User-Agent": DEFAULT_USER_AGENT, "Referer": referer},
        follow_redirects=True,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.content


def image_passes_filters(img_bytes: bytes, filters: FilterSettings) -> bool:
    try:
        with Image.open(io.BytesIO(img_bytes)) as img:
            width, height = img.size
    except Exception:
        return False

    area = width * height
    ratio = width / height if height else 0

    if width < filters.min_width or height < filters.min_height:
        return False
    if area < filters.min_area:
        return False
    if not (filters.aspect_ratio_min <= ratio <= filters.aspect_ratio_max):
        return False
    return True


def build_pdf(images: List[bytes]) -> bytes:
    page_width, page_height = landscape(A4)
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(page_width, page_height))

    for img_bytes in images:
        with Image.open(io.BytesIO(img_bytes)) as img:
            width, height = img.size
            available_w, available_h = page_width, page_height
            scale = min(available_w / width, available_h / height, 1.0)
            draw_w = width * scale
            draw_h = height * scale
            x = (page_width - draw_w) / 2
            y = (page_height - draw_h) / 2
            pdf.drawImage(ImageReader(io.BytesIO(img_bytes)), x, y, width=draw_w, height=draw_h, preserveAspectRatio=True, mask="auto")
        pdf.showPage()

    pdf.save()
    buffer.seek(0)
    return buffer.read()


@app.post("/api/process")
async def process(req: ProcessRequest):
    filters = req.filters or FilterSettings()

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            html = await fetch_html(client, str(req.url))
        except httpx.HTTPStatusError as exc:
            raise HTTPException(status_code=exc.response.status_code, detail="无法获取文章内容") from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail="抓取文章失败") from exc

        urls = extract_image_urls(html)
        if not urls:
            raise HTTPException(status_code=404, detail="未找到图片标签")

        urls = [u for u in urls if domain_allowed(u, filters.allowed_domains)]
        urls = apply_edge_trimming(urls, filters.trim_leading, filters.trim_trailing)

        if not urls:
            raise HTTPException(status_code=404, detail="过滤后没有图片 URL")

        kept_images: List[bytes] = []
        for url in urls:
            try:
                img_bytes = await download_image(client, url, str(req.url))
            except Exception:
                continue
            if image_passes_filters(img_bytes, filters):
                kept_images.append(img_bytes)

    if not kept_images:
        raise HTTPException(status_code=404, detail="没有符合条件的 PPT 图片")

    pdf_bytes = build_pdf(kept_images)
    filename = "ppt.pdf"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(io.BytesIO(pdf_bytes), media_type="application/pdf", headers=headers)


@app.post("/api/process-stream")
async def process_stream(req: ProcessRequest):
    """SSE流式返回处理进度和结果"""
    import json
    import base64

    async def event_generator():
        filters = req.filters or FilterSettings()

        try:
            # 阶段1: 获取HTML (0-10%)
            yield 'data: {"stage": "fetching_html", "progress": 0, "message": "获取文章HTML"}\n\n'

            async with httpx.AsyncClient(timeout=30) as client:
                html = await fetch_html(client, str(req.url))

            yield 'data: {"stage": "fetching_html", "progress": 10, "message": "已获取文章内容"}\n\n'

            # 阶段2: 提取URL (10-20%)
            yield 'data: {"stage": "extracting_urls", "progress": 10, "message": "解析图片链接"}\n\n'
            urls = extract_image_urls(html)
            if not urls:
                yield 'data: {"stage": "error", "error": "未找到图片标签", "error_type": "no_images"}\n\n'
                return

            yield f'data: {json.dumps({"stage": "extracting_urls", "progress": 20, "message": f"找到 {len(urls)} 张图片", "total_found": len(urls)}, ensure_ascii=False)}\n\n'

            # 阶段3: 域名过滤 (20-25%)
            yield 'data: {"stage": "filtering_domains", "progress": 20, "message": "域名过滤中"}\n\n'
            urls = [u for u in urls if domain_allowed(u, filters.allowed_domains)]
            if not urls:
                yield 'data: {"stage": "error", "error": "过滤后没有图片 URL", "error_type": "filtered_out"}\n\n'
                return

            yield f'data: {json.dumps({"stage": "filtering_domains", "progress": 25, "message": f"保留 {len(urls)} 张图片", "after_domain": len(urls)}, ensure_ascii=False)}\n\n'

            # 阶段4: 边缘裁剪 (25-30%)
            yield 'data: {"stage": "trimming_edges", "progress": 25, "message": "去除首尾图片"}\n\n'
            urls = apply_edge_trimming(urls, filters.trim_leading, filters.trim_trailing)
            if not urls:
                yield 'data: {"stage": "error", "error": "裁剪后没有图片", "error_type": "trimmed_all"}\n\n'
                return

            yield f'data: {json.dumps({"stage": "trimming_edges", "progress": 30, "message": f"剩余 {len(urls)} 张图片", "after_trim": len(urls)}, ensure_ascii=False)}\n\n'

            # 阶段5: 下载图片 (30-80%)
            kept_images = []
            total_urls = len(urls)

            async with httpx.AsyncClient(timeout=30) as client:
                for i, url in enumerate(urls):
                    progress = 30 + int((i / total_urls) * 50)
                    yield f'data: {json.dumps({"stage": "downloading_images", "progress": progress, "current": i + 1, "total": total_urls, "passed": len(kept_images), "message": "下载并验证图片"}, ensure_ascii=False)}\n\n'

                    try:
                        img_bytes = await download_image(client, url, str(req.url))
                        if image_passes_filters(img_bytes, filters):
                            kept_images.append(img_bytes)
                    except Exception:
                        continue

            if not kept_images:
                yield 'data: {"stage": "error", "error": "没有符合条件的 PPT 图片", "error_type": "no_valid_images"}\n\n'
                return

            yield f'data: {json.dumps({"stage": "downloading_images", "progress": 80, "current": total_urls, "total": total_urls, "passed": len(kept_images), "message": "图片下载完成"}, ensure_ascii=False)}\n\n'

            # 阶段6: 生成PDF (80-95%)
            total_pages = len(kept_images)
            yield f'data: {json.dumps({"stage": "generating_pdf", "progress": 80, "message": "开始生成PDF", "total_pages": total_pages}, ensure_ascii=False)}\n\n'

            # 生成PDF（简化方案：只在开始和结束发送进度）
            pdf_bytes = build_pdf(kept_images)

            yield 'data: {"stage": "generating_pdf", "progress": 95, "message": "PDF生成完成"}\n\n'

            # 阶段7: 完成 (100%)
            pdf_b64 = base64.b64encode(pdf_bytes).decode('utf-8')
            yield f'data: {json.dumps({"stage": "completed", "progress": 100, "message": "处理完成", "pdf_data": pdf_b64, "filename": "ppt.pdf"}, ensure_ascii=False)}\n\n'

        except httpx.HTTPStatusError as exc:
            error_msg = json.dumps({"stage": "error", "error": "无法获取文章内容", "error_type": "fetch_failed", "status_code": exc.response.status_code}, ensure_ascii=False)
            yield f'data: {error_msg}\n\n'
        except Exception as exc:
            error_msg = json.dumps({"stage": "error", "error": str(exc), "error_type": "unknown"}, ensure_ascii=False)
            yield f'data: {error_msg}\n\n'

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/health")
def health():
    return {"status": "ok"}


# Get the directory where the executable is located
if getattr(sys, 'frozen', False):
    # Running as compiled executable
    base_path = Path(sys._MEIPASS)
else:
    # Running as script
    base_path = Path(__file__).parent.parent

# Mount static files (frontend)
static_path = base_path / "web" / "dist"
if static_path.exists():
    app.mount("/", StaticFiles(directory=str(static_path), html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    import webbrowser
    from threading import Timer

    port = 8000

    # Open browser after a short delay
    def open_browser():
        webbrowser.open(f"http://localhost:{port}")

    Timer(1.5, open_browser).start()

    print(f"\n{'='*60}")
    print(f"  微信公众号 PPT 提取工具")
    print(f"{'='*60}")
    print(f"\n  访问地址: http://localhost:{port}")
    print(f"  按 Ctrl+C 停止服务\n")
    print(f"{'='*60}\n")

    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
