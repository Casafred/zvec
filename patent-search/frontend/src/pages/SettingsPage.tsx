import { useState, useEffect, type FormEvent } from "react"
import api from "../api"

/** 配置表单数据 */
interface ConfigForm {
  api_key: string
  model_name: string
  base_url: string
  dimension: number
}

/** GET /api/config 响应 */
interface ConfigResponse {
  api_key: string
  model_name: string
  base_url: string
  dimension: number
}

/** POST /api/config/validate 响应 */
interface ValidateResponse {
  valid: boolean
  error?: string
  dimension?: number
}

/** 设置页面 */
function SettingsPage() {
  const [form, setForm] = useState<ConfigForm>({
    api_key: "",
    model_name: "embedding-3",
    base_url: "https://open.bigmodel.cn/api/paas/v4",
    dimension: 512,
  })
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null)
  const [validating, setValidating] = useState(false)
  const [saving, setSaving] = useState(false)

  // 页面加载时获取已有配置
  useEffect(() => {
    api
      .get<ConfigResponse>("/config")
      .then((res) => {
        setForm({
          api_key: res.data.api_key || "",
          model_name: res.data.model_name || "embedding-3",
          base_url: res.data.base_url || "https://open.bigmodel.cn/api/paas/v4",
          dimension: res.data.dimension || 512,
        })
      })
      .catch(() => {
        setMessage({ type: "error", text: "加载配置失败" })
      })
  }, [])

  /** 保存配置 */
  const handleSave = async (e: FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setMessage(null)
    try {
      await api.post("/config", form)
      setMessage({ type: "success", text: "配置保存成功" })
    } catch {
      setMessage({ type: "error", text: "配置保存失败" })
    } finally {
      setSaving(false)
    }
  }

  /** 验证配置 */
  const handleValidate = async () => {
    setValidating(true)
    setMessage(null)
    try {
      const res = await api.post<ValidateResponse>("/config/validate")
      if (res.data.valid) {
        setMessage({
          type: "success",
          text: `验证成功，向量维度: ${res.data.dimension}`,
        })
      } else {
        setMessage({
          type: "error",
          text: `验证失败: ${res.data.error}`,
        })
      }
    } catch {
      setMessage({ type: "error", text: "验证请求失败" })
    } finally {
      setValidating(false)
    }
  }

  return (
    <div style={{ maxWidth: 600 }}>
      <h2 style={{ marginBottom: 24 }}>系统设置</h2>

      <form onSubmit={handleSave}>
        {/* API 密钥 */}
        <div style={{ marginBottom: 16 }}>
          <label style={{ display: "block", marginBottom: 6, fontWeight: "bold" }}>
            API 密钥
          </label>
          <input
            type="password"
            value={form.api_key}
            onChange={(e) => setForm({ ...form, api_key: e.target.value })}
            placeholder="请输入 API 密钥"
            style={{
              width: "100%",
              padding: "8px 12px",
              borderRadius: 6,
              border: "1px solid #444",
              backgroundColor: "#1a1a2e",
              color: "#eee",
              fontSize: 14,
              boxSizing: "border-box",
            }}
          />
        </div>

        {/* 模型名称 */}
        <div style={{ marginBottom: 16 }}>
          <label style={{ display: "block", marginBottom: 6, fontWeight: "bold" }}>
            模型名称
          </label>
          <input
            type="text"
            value={form.model_name}
            onChange={(e) => setForm({ ...form, model_name: e.target.value })}
            placeholder="Qwen/Qwen3-Embedding-0.6B"
            style={{
              width: "100%",
              padding: "8px 12px",
              borderRadius: 6,
              border: "1px solid #444",
              backgroundColor: "#1a1a2e",
              color: "#eee",
              fontSize: 14,
              boxSizing: "border-box",
            }}
          />
        </div>

        {/* API 地址 */}
        <div style={{ marginBottom: 16 }}>
          <label style={{ display: "block", marginBottom: 6, fontWeight: "bold" }}>
            API 地址
          </label>
          <input
            type="text"
            value={form.base_url}
            onChange={(e) => setForm({ ...form, base_url: e.target.value })}
            placeholder="https://open.bigmodel.cn/api/paas/v4"
            style={{
              width: "100%",
              padding: "8px 12px",
              borderRadius: 6,
              border: "1px solid #444",
              backgroundColor: "#1a1a2e",
              color: "#eee",
              fontSize: 14,
              boxSizing: "border-box",
            }}
          />
        </div>

        {/* 向量维度 */}
        <div style={{ marginBottom: 16 }}>
          <label style={{ display: "block", marginBottom: 6, fontWeight: "bold" }}>
            向量维度
          </label>
          <select
            value={form.dimension}
            onChange={(e) => setForm({ ...form, dimension: Number(e.target.value) })}
            style={{
              width: "100%",
              padding: "8px 12px",
              borderRadius: 6,
              border: "1px solid #444",
              backgroundColor: "#1a1a2e",
              color: "#eee",
              fontSize: 14,
              boxSizing: "border-box",
              cursor: "pointer",
            }}
          >
            <option value={256}>256 维（高效）</option>
            <option value={512}>512 维（均衡，推荐）</option>
            <option value={1024}>1024 维（高精度）</option>
            <option value={2048}>2048 维（最高精度）</option>
          </select>
          <p style={{ margin: "4px 0 0", fontSize: 12, color: "#888" }}>
            维度越高精度越好，但存储和计算成本也越高。切换维度需删除已有数据重新导入。
          </p>
        </div>

        {/* 按钮组 */}
        <div style={{ display: "flex", gap: 12, marginTop: 24 }}>
          <button
            type="submit"
            disabled={saving}
            style={{
              padding: "8px 24px",
              borderRadius: 6,
              border: "none",
              backgroundColor: "#4fc3f7",
              color: "#1a1a2e",
              fontWeight: "bold",
              cursor: saving ? "not-allowed" : "pointer",
              opacity: saving ? 0.6 : 1,
            }}
          >
            {saving ? "保存中..." : "保存"}
          </button>
          <button
            type="button"
            onClick={handleValidate}
            disabled={validating}
            style={{
              padding: "8px 24px",
              borderRadius: 6,
              border: "1px solid #4fc3f7",
              backgroundColor: "transparent",
              color: "#4fc3f7",
              fontWeight: "bold",
              cursor: validating ? "not-allowed" : "pointer",
              opacity: validating ? 0.6 : 1,
            }}
          >
            {validating ? "验证中..." : "验证"}
          </button>
        </div>
      </form>

      {/* 消息提示 */}
      {message && (
        <div
          style={{
            marginTop: 20,
            padding: "10px 16px",
            borderRadius: 6,
            backgroundColor: message.type === "success" ? "#1b5e20" : "#b71c1c",
            color: "#fff",
            fontSize: 14,
          }}
        >
          {message.text}
        </div>
      )}
    </div>
  )
}

export default SettingsPage
