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
