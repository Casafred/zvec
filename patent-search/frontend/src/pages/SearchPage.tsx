import { useState, useEffect, type FormEvent } from "react"
import api from "../api"

/** 搜索结果条目 */
interface SearchHit {
  id: string
  score: number
  patent_no: string
  applicant: string
  title: string
  abstract: string
  description: string
  claims: string
}

/** 搜索响应 */
interface SearchResponse {
  results: SearchHit[]
}

/** 搜索状态响应 */
interface StatusResponse {
  available: boolean
  document_count: number
}

/** 截断文本 */
function truncate(text: string, maxLen: number): string {
  if (!text) return ""
  return text.length > maxLen ? text.slice(0, maxLen) + "..." : text
}

/** 相似度分数转百分比 */
function scoreToPercent(score: number): string {
  // 将分数映射到 0~100% 范围
  const percent = Math.max(0, Math.min(100, score * 100))
  return percent.toFixed(1) + "%"
}

/** 搜索页面 */
function SearchPage() {
  const [query, setQuery] = useState("")
  const [applicant, setApplicant] = useState("")
  const [topk, setTopk] = useState(10)
  const [results, setResults] = useState<SearchHit[]>([])
  const [loading, setLoading] = useState(false)
  const [searched, setSearched] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [status, setStatus] = useState<StatusResponse | null>(null)

  // 页面加载时检查搜索状态
  useEffect(() => {
    api
      .get<StatusResponse>("/search/status")
      .then((res) => setStatus(res.data))
      .catch(() => setStatus({ available: false, document_count: 0 }))
  }, [])

  /** 执行搜索 */
  const handleSearch = async (e: FormEvent) => {
    e.preventDefault()
    if (!query.trim()) return

    setLoading(true)
    setError(null)
    setSearched(true)
    setExpandedId(null)

    try {
      const params: Record<string, unknown> = {
        query: query.trim(),
        topk,
      }
      if (applicant.trim()) {
        params.applicant = applicant.trim()
      }
      const res = await api.post<SearchResponse>("/search", params)
      setResults(res.data.results)
    } catch (err: unknown) {
      if (import.meta.env.DEV) {
        // 开发环境详细错误
        if (err && typeof err === "object" && "response" in err) {
          const axiosErr = err as { response?: { data?: { detail?: string } } }
          setError(axiosErr.response?.data?.detail || "搜索失败，请重试")
        } else {
          setError("搜索失败，请重试")
        }
      } else {
        setError("搜索失败，请重试")
      }
      setResults([])
    } finally {
      setLoading(false)
    }
  }

  /** 切换展开/折叠 */
  const toggleExpand = (id: string) => {
    setExpandedId((prev) => (prev === id ? null : id))
  }

  // 数据库不可用时的空状态
  if (status && !status.available) {
    return (
      <div style={{ textAlign: "center", padding: "80px 20px" }}>
        <p style={{ fontSize: 18, color: "#999" }}>暂无数据，请先导入专利</p>
      </div>
    )
  }

  return (
    <div style={{ maxWidth: 960, margin: "0 auto" }}>
      {/* 搜索表单 */}
      <form onSubmit={handleSearch}>
        {/* 主搜索框 */}
        <div style={{ marginBottom: 16 }}>
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="输入关键词或描述搜索专利..."
            style={{
              width: "100%",
              padding: "14px 18px",
              borderRadius: 8,
              border: "1px solid #444",
              backgroundColor: "#2a2a3e",
              color: "#eee",
              fontSize: 18,
              boxSizing: "border-box",
              outline: "none",
              transition: "border-color 0.2s",
            }}
            onFocus={(e) => (e.target.style.borderColor = "#4fc3f7")}
            onBlur={(e) => (e.target.style.borderColor = "#444")}
          />
        </div>

        {/* 过滤与选项行 */}
        <div
          style={{
            display: "flex",
            gap: 12,
            alignItems: "center",
            marginBottom: 24,
          }}
        >
          {/* 申请人过滤 */}
          <input
            type="text"
            value={applicant}
            onChange={(e) => setApplicant(e.target.value)}
            placeholder="按申请人过滤（可选）"
            style={{
              flex: 1,
              padding: "10px 14px",
              borderRadius: 6,
              border: "1px solid #444",
              backgroundColor: "#2a2a3e",
              color: "#eee",
              fontSize: 14,
              boxSizing: "border-box",
              outline: "none",
              transition: "border-color 0.2s",
            }}
            onFocus={(e) => (e.target.style.borderColor = "#4fc3f7")}
            onBlur={(e) => (e.target.style.borderColor = "#444")}
          />

          {/* TopK 选择器 */}
          <select
            value={topk}
            onChange={(e) => setTopk(Number(e.target.value))}
            style={{
              padding: "10px 14px",
              borderRadius: 6,
              border: "1px solid #444",
              backgroundColor: "#2a2a3e",
              color: "#eee",
              fontSize: 14,
              cursor: "pointer",
              outline: "none",
            }}
          >
            <option value={5}>Top 5</option>
            <option value={10}>Top 10</option>
            <option value={20}>Top 20</option>
            <option value={50}>Top 50</option>
          </select>

          {/* 搜索按钮 */}
          <button
            type="submit"
            disabled={loading || !query.trim()}
            style={{
              padding: "10px 28px",
              borderRadius: 6,
              border: "none",
              backgroundColor: "#4fc3f7",
              color: "#1a1a2e",
              fontSize: 15,
              fontWeight: "bold",
              cursor: loading || !query.trim() ? "not-allowed" : "pointer",
              opacity: loading || !query.trim() ? 0.6 : 1,
              whiteSpace: "nowrap",
            }}
          >
            {loading ? "搜索中..." : "搜索"}
          </button>
        </div>
      </form>

      {/* 错误提示 */}
      {error && (
        <div
          style={{
            padding: "12px 16px",
            borderRadius: 6,
            backgroundColor: "rgba(244, 67, 54, 0.15)",
            color: "#ef5350",
            marginBottom: 24,
          }}
        >
          {error}
        </div>
      )}

      {/* 加载状态 */}
      {loading && (
        <div style={{ textAlign: "center", padding: "40px 0" }}>
          <p style={{ color: "#4fc3f7", fontSize: 16 }}>正在搜索...</p>
        </div>
      )}

      {/* 搜索结果 */}
      {!loading && searched && results.length === 0 && !error && (
        <div style={{ textAlign: "center", padding: "40px 0" }}>
          <p style={{ color: "#999", fontSize: 16 }}>未找到相关专利</p>
        </div>
      )}

      {!loading && results.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {results.map((hit) => {
            const isExpanded = expandedId === hit.id
            return (
              <div
                key={hit.id}
                onClick={() => toggleExpand(hit.id)}
                style={{
                  padding: "16px 20px",
                  borderRadius: 8,
                  backgroundColor: "#2a2a3e",
                  border: `1px solid ${isExpanded ? "#4fc3f7" : "#3a3a4e"}`,
                  cursor: "pointer",
                  transition: "border-color 0.2s",
                }}
              >
                {/* 标题行 */}
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "flex-start",
                    marginBottom: 6,
                  }}
                >
                  <h3
                    style={{
                      margin: 0,
                      fontSize: 17,
                      color: "#eee",
                      fontWeight: 600,
                      flex: 1,
                      marginRight: 12,
                    }}
                  >
                    {hit.title || "无标题"}
                  </h3>
                  <span
                    style={{
                      fontSize: 14,
                      color: "#4fc3f7",
                      fontWeight: "bold",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {scoreToPercent(hit.score)}
                  </span>
                </div>

                {/* 专利号与申请人 */}
                <div
                  style={{
                    fontSize: 13,
                    color: "#888",
                    marginBottom: 8,
                  }}
                >
                  {hit.patent_no && <span>{hit.patent_no}</span>}
                  {hit.patent_no && hit.applicant && (
                    <span> · </span>
                  )}
                  {hit.applicant && <span>{hit.applicant}</span>}
                </div>

                {/* 摘要 */}
                <p
                  style={{
                    margin: 0,
                    fontSize: 14,
                    color: "#bbb",
                    lineHeight: 1.6,
                  }}
                >
                  {isExpanded ? hit.abstract : truncate(hit.abstract, 100)}
                </p>

                {/* 展开内容：说明书 */}
                {isExpanded && hit.description && (
                  <div style={{ marginTop: 12 }}>
                    <h4
                      style={{
                        margin: "0 0 6px",
                        fontSize: 14,
                        color: "#4fc3f7",
                      }}
                    >
                      说明书
                    </h4>
                    <p
                      style={{
                        margin: 0,
                        fontSize: 13,
                        color: "#aaa",
                        lineHeight: 1.6,
                        whiteSpace: "pre-wrap",
                        maxHeight: 300,
                        overflowY: "auto",
                      }}
                    >
                      {hit.description}
                    </p>
                  </div>
                )}

                {/* 展开内容：权利要求 */}
                {isExpanded && hit.claims && (
                  <div style={{ marginTop: 12 }}>
                    <h4
                      style={{
                        margin: "0 0 6px",
                        fontSize: 14,
                        color: "#4fc3f7",
                      }}
                    >
                      权利要求
                    </h4>
                    <p
                      style={{
                        margin: 0,
                        fontSize: 13,
                        color: "#aaa",
                        lineHeight: 1.6,
                        whiteSpace: "pre-wrap",
                        maxHeight: 300,
                        overflowY: "auto",
                      }}
                    >
                      {hit.claims}
                    </p>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

export default SearchPage
