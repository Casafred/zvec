import { useState, useRef, useEffect, type DragEvent, type ChangeEvent } from 'react'
import { Link } from 'react-router-dom'
import axios from 'axios'

/** 专利字段定义 */
const PATENT_FIELDS = [
  { key: 'patent_no', label: '专利号' },
  { key: 'applicant', label: '申请人' },
  { key: 'title', label: '标题' },
  { key: 'abstract', label: '摘要' },
  { key: 'description', label: '说明书' },
  { key: 'claims', label: '权利要求' },
] as const

type PatentFieldKey = (typeof PATENT_FIELDS)[number]['key']

/** 上传接口返回的数据结构 */
interface UploadResult {
  upload_id: string
  columns: string[]
  preview: Record<string, unknown>[]
  mapping: Record<string, string | null>
  total_rows: number
}

/** 导入接口返回的数据结构 */
interface ImportResult {
  total: number
  imported: number
  failed: number
  error: string | null
}

/** 集合状态接口返回的数据结构 */
interface CollectionStatus {
  collection_exists: boolean
  document_count: number
  dimension: number | null
}

/** 导入页面 */
function ImportPage() {
  // 上传状态
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [uploadResult, setUploadResult] = useState<UploadResult | null>(null)

  // 拖拽状态
  const [dragging, setDragging] = useState(false)

  // 列映射状态
  const [mapping, setMapping] = useState<Record<string, string | null>>({})
  const [mappingConfirmed, setMappingConfirmed] = useState(false)

  // 导入状态
  const [importing, setImporting] = useState(false)
  const [importResult, setImportResult] = useState<ImportResult | null>(null)
  const [importError, setImportError] = useState<string | null>(null)

  // 集合状态
  const [collectionStatus, setCollectionStatus] = useState<CollectionStatus | null>(null)

  const fileInputRef = useRef<HTMLInputElement>(null)

  /** 获取集合状态 */
  useEffect(() => {
    axios
      .get<CollectionStatus>('/api/import/status')
      .then((res) => setCollectionStatus(res.data))
      .catch(() => {
        // 忽略错误，集合可能不存在
      })
  }, [importResult]) // 导入完成后刷新状态

  /** 上传文件到后端 */
  const uploadFile = async (file: File) => {
    if (!file.name.endsWith('.xlsx') && !file.name.endsWith('.xls')) {
      setUploadError('仅支持 .xlsx 和 .xls 格式的文件')
      return
    }

    setUploading(true)
    setUploadError(null)
    setUploadResult(null)
    setMappingConfirmed(false)
    setImportResult(null)
    setImportError(null)

    const formData = new FormData()
    formData.append('file', file)

    try {
      const response = await axios.post<UploadResult>('/api/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setUploadResult(response.data)
      setMapping(response.data.mapping)
    } catch (err: unknown) {
      if (axios.isAxiosError(err) && err.response?.data?.detail) {
        setUploadError(err.response.data.detail)
      } else {
        setUploadError('上传失败，请重试')
      }
    } finally {
      setUploading(false)
    }
  }

  /** 拖拽事件处理 */
  const handleDragOver = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setDragging(true)
  }

  const handleDragLeave = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setDragging(false)
  }

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setDragging(false)
    const file = e.dataTransfer.files[0]
    if (file) uploadFile(file)
  }

  /** 点击选择文件 */
  const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) uploadFile(file)
  }

  /** 映射下拉变更 */
  const handleMappingChange = (fieldKey: PatentFieldKey, value: string) => {
    setMapping((prev) => ({
      ...prev,
      [fieldKey]: value || null,
    }))
  }

  /** 确认映射 */
  const handleConfirmMapping = () => {
    setMappingConfirmed(true)
  }

  /** 开始导入 */
  const handleStartImport = async () => {
    if (!uploadResult) return

    setImporting(true)
    setImportError(null)
    setImportResult(null)

    try {
      const response = await axios.post<ImportResult>('/api/import', {
        upload_id: uploadResult.upload_id,
        mapping,
      })
      setImportResult(response.data)
      if (response.data.error) {
        setImportError(response.data.error)
      }
    } catch (err: unknown) {
      if (axios.isAxiosError(err) && err.response?.data?.detail) {
        setImportError(err.response.data.detail)
      } else {
        setImportError('导入失败，请重试')
      }
    } finally {
      setImporting(false)
    }
  }

  return (
    <div style={{ maxWidth: 960, margin: '0 auto' }}>
      <h2 style={{ marginBottom: 24 }}>数据导入</h2>

      {/* 集合状态提示 */}
      {collectionStatus?.collection_exists && (
        <div
          style={{
            padding: '12px 16px',
            borderRadius: 6,
            backgroundColor: 'rgba(79, 195, 247, 0.1)',
            color: '#4fc3f7',
            marginBottom: 24,
            fontSize: 14,
          }}
        >
          当前已有 <strong>{collectionStatus.document_count}</strong> 条专利数据
          {collectionStatus.dimension && (
            <span style={{ marginLeft: 12, color: '#999' }}>
              向量维度：{collectionStatus.dimension}
            </span>
          )}
        </div>
      )}

      {/* 文件上传区域 */}
      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
        style={{
          border: `2px dashed ${dragging ? '#4fc3f7' : '#555'}`,
          borderRadius: 8,
          padding: '48px 24px',
          textAlign: 'center',
          cursor: 'pointer',
          backgroundColor: dragging ? 'rgba(79, 195, 247, 0.08)' : 'transparent',
          transition: 'all 0.2s',
          marginBottom: 24,
        }}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept=".xlsx,.xls"
          onChange={handleFileChange}
          style={{ display: 'none' }}
        />
        {uploading ? (
          <p style={{ color: '#4fc3f7', fontSize: 16 }}>上传中...</p>
        ) : (
          <>
            <p style={{ fontSize: 16, color: '#ccc', margin: 0 }}>
              拖拽 Excel 文件到此处，或点击选择文件
            </p>
            <p style={{ fontSize: 13, color: '#888', marginTop: 8 }}>
              支持 .xlsx 和 .xls 格式
            </p>
          </>
        )}
      </div>

      {/* 上传错误提示 */}
      {uploadError && (
        <div
          style={{
            padding: '12px 16px',
            borderRadius: 6,
            backgroundColor: 'rgba(244, 67, 54, 0.15)',
            color: '#ef5350',
            marginBottom: 24,
          }}
        >
          {uploadError}
        </div>
      )}

      {/* 上传成功后的预览 */}
      {uploadResult && (
        <>
          {/* 统计信息 */}
          <div
            style={{
              display: 'flex',
              gap: 16,
              marginBottom: 24,
            }}
          >
            <div
              style={{
                padding: '12px 20px',
                borderRadius: 6,
                backgroundColor: 'rgba(79, 195, 247, 0.1)',
                color: '#4fc3f7',
                fontSize: 14,
              }}
            >
              共 <strong>{uploadResult.total_rows}</strong> 行数据
            </div>
            <div
              style={{
                padding: '12px 20px',
                borderRadius: 6,
                backgroundColor: 'rgba(79, 195, 247, 0.1)',
                color: '#4fc3f7',
                fontSize: 14,
              }}
            >
              共 <strong>{uploadResult.columns.length}</strong> 列
            </div>
          </div>

          {/* 预览表格 */}
          <div style={{ marginBottom: 32 }}>
            <h3 style={{ marginBottom: 12, color: '#eee', fontSize: 18 }}>
              数据预览（前 5 行）
            </h3>
            <div style={{ overflowX: 'auto' }}>
              <table
                style={{
                  width: '100%',
                  borderCollapse: 'collapse',
                  fontSize: 13,
                }}
              >
                <thead>
                  <tr>
                    {uploadResult.columns.map((col) => (
                      <th
                        key={col}
                        style={{
                          padding: '8px 12px',
                          borderBottom: '2px solid #444',
                          textAlign: 'left',
                          color: '#aaa',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {col}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {uploadResult.preview.map((row, i) => (
                    <tr key={i}>
                      {uploadResult.columns.map((col) => (
                        <td
                          key={col}
                          style={{
                            padding: '8px 12px',
                            borderBottom: '1px solid #333',
                            color: '#ccc',
                            maxWidth: 200,
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                          }}
                        >
                          {String(row[col] ?? '')}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* 列名映射区域 */}
          <div style={{ marginBottom: 32 }}>
            <h3 style={{ marginBottom: 12, color: '#eee', fontSize: 18 }}>
              列名映射
            </h3>
            <p style={{ color: '#999', fontSize: 14, marginBottom: 16 }}>
              为每个专利字段选择对应的 Excel 列名
            </p>

            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
                gap: 16,
              }}
            >
              {PATENT_FIELDS.map((field) => (
                <div
                  key={field.key}
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 6,
                  }}
                >
                  <label
                    style={{
                      fontSize: 14,
                      fontWeight: 'bold',
                      color: '#ccc',
                    }}
                  >
                    {field.label}
                  </label>
                  <select
                    value={mapping[field.key] || ''}
                    onChange={(e) =>
                      handleMappingChange(field.key, e.target.value)
                    }
                    style={{
                      padding: '8px 12px',
                      borderRadius: 6,
                      border: '1px solid #555',
                      backgroundColor: '#2a2a3e',
                      color: '#eee',
                      fontSize: 14,
                      cursor: 'pointer',
                    }}
                  >
                    <option value="">-- 未映射 --</option>
                    {uploadResult.columns.map((col) => (
                      <option key={col} value={col}>
                        {col}
                      </option>
                    ))}
                  </select>
                </div>
              ))}
            </div>

            <button
              onClick={handleConfirmMapping}
              style={{
                marginTop: 20,
                padding: '10px 28px',
                borderRadius: 6,
                border: 'none',
                backgroundColor: '#4fc3f7',
                color: '#1a1a2e',
                fontSize: 15,
                fontWeight: 'bold',
                cursor: 'pointer',
              }}
            >
              确认映射
            </button>

            {mappingConfirmed && (
              <div
                style={{
                  marginTop: 12,
                  padding: '10px 16px',
                  borderRadius: 6,
                  backgroundColor: 'rgba(76, 175, 80, 0.15)',
                  color: '#66bb6a',
                  fontSize: 14,
                }}
              >
                映射已确认，上传 ID：{uploadResult.upload_id}
              </div>
            )}
          </div>

          {/* 开始导入按钮 */}
          {mappingConfirmed && !importResult && (
            <div style={{ marginBottom: 32 }}>
              <button
                onClick={handleStartImport}
                disabled={importing}
                style={{
                  padding: '12px 36px',
                  borderRadius: 6,
                  border: 'none',
                  backgroundColor: importing ? '#555' : '#4fc3f7',
                  color: importing ? '#999' : '#1a1a2e',
                  fontSize: 16,
                  fontWeight: 'bold',
                  cursor: importing ? 'not-allowed' : 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                }}
              >
                {importing && (
                  <span
                    style={{
                      display: 'inline-block',
                      width: 16,
                      height: 16,
                      border: '2px solid #999',
                      borderTopColor: 'transparent',
                      borderRadius: '50%',
                      animation: 'spin 0.8s linear infinite',
                    }}
                  />
                )}
                {importing ? '导入中...' : '开始导入'}
              </button>
            </div>
          )}

          {/* 导入中加载动画样式 */}
          <style>{`
            @keyframes spin {
              to { transform: rotate(360deg); }
            }
          `}</style>

          {/* 导入错误提示 */}
          {importError && (
            <div
              style={{
                padding: '12px 16px',
                borderRadius: 6,
                backgroundColor: 'rgba(244, 67, 54, 0.15)',
                color: '#ef5350',
                marginBottom: 24,
              }}
            >
              <div>导入失败：{importError}</div>
              {importResult && importResult.imported > 0 && (
                <div style={{ marginTop: 4, color: '#ffab91', fontSize: 13 }}>
                  已成功导入 {importResult.imported} 条数据后发生错误
                </div>
              )}
            </div>
          )}

          {/* 导入成功提示 */}
          {importResult && !importError && (
            <div
              style={{
                padding: '16px 20px',
                borderRadius: 6,
                backgroundColor: 'rgba(76, 175, 80, 0.15)',
                color: '#66bb6a',
                marginBottom: 24,
              }}
            >
              <div style={{ fontSize: 16, fontWeight: 'bold', marginBottom: 8 }}>
                导入完成！共导入 {importResult.imported} 条专利数据
              </div>
              {importResult.failed > 0 && (
                <div style={{ fontSize: 13, color: '#a5d6a7' }}>
                  其中 {importResult.failed} 条数据因文本为空被跳过
                </div>
              )}
              <Link
                to="/"
                style={{
                  display: 'inline-block',
                  marginTop: 12,
                  padding: '8px 20px',
                  borderRadius: 6,
                  backgroundColor: '#66bb6a',
                  color: '#1a1a2e',
                  textDecoration: 'none',
                  fontSize: 14,
                  fontWeight: 'bold',
                }}
              >
                前往搜索
              </Link>
            </div>
          )}
        </>
      )}
    </div>
  )
}

export default ImportPage
