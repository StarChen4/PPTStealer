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

  // 新增：状态显示相关状态
  const [statusVisible, setStatusVisible] = useState(false);
  const [stage, setStage] = useState("idle");
  const [progress, setProgress] = useState(0);
  const [statusMessage, setStatusMessage] = useState("");
  const [statusDetails, setStatusDetails] = useState({});
  const [useSSE, setUseSSE] = useState(true);

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

  // Base64转Blob
  const base64ToBlob = (base64, type) => {
    const binary = atob(base64);
    const array = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
      array[i] = binary.charCodeAt(i);
    }
    return new Blob([array], { type });
  };

  // 错误信息增强
  const getEnhancedErrorMessage = (error, errorType) => {
    const errorMap = {
      no_images: "❌ 文章中未找到图片\n💡 可能原因：\n• 文章不包含PPT图片\n• 页面未完全加载\n• 文章格式不支持",
      filtered_out: "❌ 域名过滤后无图片\n💡 建议操作：\n• 检查「允许域名」设置\n• 尝试添加更多域名\n• 关闭域名过滤功能",
      no_valid_images: "❌ 没有符合过滤条件的图片\n💡 建议调整：\n• 降低「最小宽度/高度」\n• 扩大「宽高比」范围\n• 减少「去除张数」设置",
      fetch_failed: "❌ 无法获取文章内容\n💡 请检查：\n• URL是否正确完整\n• 文章是否已被删除\n• 网络连接是否正常"
    };

    return errorMap[errorType] || `❌ ${error}`;
  };

  // SSE处理函数
  const handleSubmitWithSSE = async (urlValue, filtersValue) => {
    setStatusVisible(true);
    setStage("idle");
    setProgress(0);
    setError("");
    setDownloadUrl("");

    try {
      const response = await fetch("/api/process-stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: urlValue, filters: filtersValue })
      });

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop(); // 保留不完整的行

        for (const line of lines) {
          if (line.startsWith("data: ")) {
            const data = JSON.parse(line.slice(6));

            setStage(data.stage);
            setProgress(data.progress || 0);
            setStatusMessage(data.message || "");
            setStatusDetails({
              current: data.current,
              total: data.total,
              passed: data.passed,
              totalFound: data.total_found,
              currentPage: data.current_page,
              totalPages: data.total_pages
            });

            // 处理完成
            if (data.stage === "completed") {
              const pdfBlob = base64ToBlob(data.pdf_data, "application/pdf");
              const pdfUrl = URL.createObjectURL(pdfBlob);
              setDownloadUrl(pdfUrl);
              setFilename(data.filename || "ppt.pdf");
            }

            // 处理错误
            if (data.stage === "error") {
              setError(getEnhancedErrorMessage(data.error, data.error_type));
              setStatusVisible(false);
            }
          }
        }
      }
    } catch (err) {
      console.error("SSE处理失败，降级到普通模式", err);
      setUseSSE(false);
      setStatusVisible(false);
      // 降级到原有的fetch方式
      await handleSubmitClassic(urlValue, filtersValue);
    }
  };

  // 原有的Classic模式（降级方案）
  const handleSubmitClassic = async (urlValue, filtersValue) => {
    try {
      const resp = await fetch("/api/process", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url: urlValue,
          filters: {
            ...filtersValue,
            allowed_domains: filtersValue.allowed_domains,
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
      throw err;
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setDownloadUrl("");
    setLoading(true);

    try {
      if (useSSE) {
        await handleSubmitWithSSE(url, filters);
      } else {
        await handleSubmitClassic(url, filters);
      }
    } catch (err) {
      setError(err.message || "发生未知错误");
    } finally {
      setLoading(false);
    }
  };

  const resetFilters = () => {
    setFilters(defaultFilters);
  };

  const renderStatusCard = () => {
    if (!statusVisible) return null;

    const stageEmojis = {
      fetching_html: "📄",
      extracting_urls: "🔍",
      filtering_domains: "🎯",
      trimming_edges: "✂️",
      downloading_images: "⬇️",
      generating_pdf: "📑",
      completed: "✅"
    };

    const stageNames = {
      fetching_html: "获取文章HTML",
      extracting_urls: "解析图片链接",
      filtering_domains: "域名过滤",
      trimming_edges: "边缘裁剪",
      downloading_images: "下载并验证图片",
      generating_pdf: "生成PDF文档",
      completed: "处理完成"
    };

    const emoji = stageEmojis[stage] || "⏳";
    const stageName = stageNames[stage] || statusMessage;

    // 构建详细信息
    let detailText = "";
    if (stage === "downloading_images" && statusDetails.total) {
      detailText = `（已通过 ${statusDetails.passed || 0}/${statusDetails.total} 张）`;
    } else if (stage === "generating_pdf" && statusDetails.totalPages) {
      detailText = `（第 ${statusDetails.currentPage || 0}/${statusDetails.totalPages} 页）`;
    } else if (stage === "extracting_urls" && statusDetails.totalFound) {
      detailText = `（找到 ${statusDetails.totalFound} 张）`;
    }

    return (
      <div className="status-card">
        <div className="status-header">
          <span className="status-emoji">{emoji}</span>
          <span className="status-title">处理状态</span>
        </div>

        <div className="progress-bar-container">
          <div className="progress-bar" style={{ width: `${progress}%` }}></div>
        </div>

        <div className="status-text">
          {emoji} {stageName}{detailText} {progress}%
        </div>

        {stage === "completed" && (
          <div className="status-hint warning">
            ⚠️ 提示：生成的PPT内容过多时，下载需要等待较长时间，请耐心等待
          </div>
        )}
      </div>
    );
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

        {renderStatusCard()}

        {renderDownload()}
      </main>
    </div>
  );
}

export default App;
