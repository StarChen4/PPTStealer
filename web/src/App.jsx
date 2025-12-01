import { useMemo, useState } from "react";

const defaultFilters = {
  allowed_domains: ["mmbiz.qpic.cn"],
  min_area: 300000,
  min_width: 600,
  min_height: 400,
  aspect_ratio_min: 0.6,
  aspect_ratio_max: 1.8,
  trim_leading: 2,
  trim_trailing: 2,
};

function App() {
  const [url, setUrl] = useState("");
  const [filters, setFilters] = useState(defaultFilters);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [downloadUrl, setDownloadUrl] = useState("");
  const [filename, setFilename] = useState("ppt.pdf");
  const [showAdvanced, setShowAdvanced] = useState(false);

  const filterList = useMemo(
    () => [
      { key: "min_width", label: "最小宽度 (px)" },
      { key: "min_height", label: "最小高度 (px)" },
      { key: "min_area", label: "最小像素面积" },
      { key: "aspect_ratio_min", label: "最小宽高比" },
      { key: "aspect_ratio_max", label: "最大宽高比" },
      { key: "trim_leading", label: "去除开头张数" },
      { key: "trim_trailing", label: "去除结尾张数" },
    ],
    [],
  );

  const handleChange = (key, value) => {
    setFilters((prev) => ({ ...prev, [key]: value }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setDownloadUrl("");
    setLoading(true);

    try {
      const resp = await fetch("/api/process", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url,
          filters: {
            ...filters,
            allowed_domains: filters.allowed_domains,
          },
        }),
      });

      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}));
        throw new Error(data.detail || "生成失败，请稍后重试");
      }

      const blob = await resp.blob();
      const file = resp.headers.get("Content-Disposition");
      if (file) {
        const match = /filename=\"?([^\";]+)\"?/i.exec(file);
        if (match?.[1]) {
          setFilename(match[1]);
        }
      }

      const urlObj = URL.createObjectURL(blob);
      setDownloadUrl(urlObj);
    } catch (err) {
      setError(err.message || "发生未知错误");
    } finally {
      setLoading(false);
    }
  };

  const resetFilters = () => {
    setFilters(defaultFilters);
  };

  const renderDownload = () => {
    if (!downloadUrl) return null;
    return (
      <div className="download-card">
        <p>PDF 已生成</p>
        <a className="button primary" href={downloadUrl} download={filename}>
          下载 PDF
        </a>
      </div>
    );
  };

  return (
    <div className="page">
      <header className="hero">
        <div>
          <p className="eyebrow">WeChat PPT → PDF</p>
          <h1>一键提取公众号 PPT 并生成 A4 横版 PDF</h1>
          <p className="lede">
            自动抓取文章中的 PPT 图片，按顺序过滤、缩放并合成 PDF。默认规则可在高级设置中调整。
          </p>
        </div>
      </header>

      <main className="panel">
        <form onSubmit={handleSubmit} className="form">
          <label className="label">文章链接</label>
          <div className="input-row">
            <input
              type="url"
              placeholder="https://mp.weixin.qq.com/s/xxxx"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              required
            />
            <button className="button primary" type="submit" disabled={loading}>
              {loading ? "生成中..." : "生成 PDF"}
            </button>
          </div>
          <p className="hint">仅抓取公众号页面中的 PPT 图片，过滤广告/二维码首尾等无关图。</p>

          <div className="toggle-row">
            <button
              type="button"
              className="button ghost"
              onClick={() => setShowAdvanced((v) => !v)}
            >
              {showAdvanced ? "收起高级设置" : "展开高级设置"}
            </button>
            <button type="button" className="button ghost" onClick={resetFilters}>
              恢复默认规则
            </button>
          </div>

          {showAdvanced && (
            <div className="grid">
              <div className="input-group full">
                <label>允许域名（逗号分隔）</label>
                <input
                  type="text"
                  value={filters.allowed_domains.join(",")}
                  onChange={(e) =>
                    handleChange(
                      "allowed_domains",
                      e.target.value
                        .split(",")
                        .map((v) => v.trim())
                        .filter(Boolean),
                    )
                  }
                />
              </div>
              {filterList.map(({ key, label }) => (
                <div className="input-group" key={key}>
                  <label>{label}</label>
                  <input
                    type="number"
                    step={key.includes("aspect_ratio") ? "0.1" : "1"}
                    value={filters[key]}
                    onChange={(e) =>
                      handleChange(key, Number(e.target.value))
                    }
                  />
                </div>
              ))}
            </div>
          )}

          {error && <div className="error">{error}</div>}
        </form>

        {renderDownload()}
      </main>
    </div>
  );
}

export default App;
