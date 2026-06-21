"""数据导入路由"""
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from openai import OpenAI
from pydantic import BaseModel, Field
import zvec

from app.collection_manager import get_or_create_collection, get_collection, COLLECTION_PATH

router = APIRouter(prefix="/api/import", tags=["导入"])

# 数据目录
UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "uploaded"
CONFIG_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "config.json"

# 批量参数
EMBEDDING_BATCH_SIZE = 50
INSERT_BATCH_SIZE = 100


class ImportRequest(BaseModel):
    """导入请求"""
    upload_id: str = Field(..., description="上传文件 ID")
    mapping: dict[str, str | None] = Field(..., description="字段映射关系")


class ImportResponse(BaseModel):
    """导入响应"""
    total: int = Field(..., description="总行数")
    imported: int = Field(..., description="成功导入行数")
    failed: int = Field(..., description="失败行数")
    error: str | None = Field(default=None, description="错误信息")


class StatusResponse(BaseModel):
    """集合状态响应"""
    collection_exists: bool = Field(..., description="集合是否存在")
    document_count: int = Field(default=0, description="文档数量")
    dimension: int | None = Field(default=None, description="向量维度")


def _read_config() -> dict:
    """读取 API 配置"""
    if not CONFIG_FILE.exists():
        raise HTTPException(status_code=400, detail="未找到配置，请先在设置页面配置 API 密钥")
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _build_text(row: dict, mapping: dict[str, str | None]) -> str:
    """根据映射关系拼接文本：标题 + 摘要 + 权利要求"""
    parts = []
    for field_key in ("title", "abstract", "claims"):
        col_name = mapping.get(field_key)
        if col_name and col_name in row:
            value = str(row[col_name]).strip()
            if value:
                parts.append(value)
    return "\n".join(parts)


def _generate_embeddings(
    texts: list[str],
    api_key: str,
    model_name: str,
    base_url: str,
) -> list[list[float]]:
    """调用 OpenAI 兼容接口生成向量"""
    client = OpenAI(api_key=api_key, base_url=base_url)
    response = client.embeddings.create(model=model_name, input=texts)
    # 按 index 排序确保顺序一致
    sorted_data = sorted(response.data, key=lambda x: x.index)
    return [item.embedding for item in sorted_data]


@router.post("", response_model=ImportResponse)
def import_data(req: ImportRequest):
    """从已上传的 Excel 文件导入数据到向量集合"""
    # 1. 读取上传的 JSON 数据
    json_path = UPLOAD_DIR / f"{req.upload_id}.json"
    if not json_path.exists():
        raise HTTPException(status_code=404, detail="上传文件不存在，请重新上传")

    with open(json_path, "r", encoding="utf-8") as f:
        rows: list[dict] = json.load(f)

    if not rows:
        raise HTTPException(status_code=400, detail="上传文件中没有数据")

    # 2. 读取配置
    config = _read_config()
    api_key = config.get("api_key", "")
    model_name = config.get("model_name", "text-embedding-v3")
    base_url = config.get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1")

    if not api_key:
        raise HTTPException(status_code=400, detail="API 密钥为空，请先在设置页面配置")

    # 3. 先用一条数据探测向量维度
    first_text = _build_text(rows[0], req.mapping)
    if not first_text.strip():
        raise HTTPException(status_code=400, detail="第一条数据拼接文本为空，请检查映射关系")

    try:
        first_embeddings = _generate_embeddings([first_text], api_key, model_name, base_url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"调用嵌入接口失败: {e}")

    dimension = len(first_embeddings[0])

    # 4. 获取或创建集合
    collection = get_or_create_collection(dimension)

    # 5. 插入第一条数据
    first_row = rows[0]
    patent_no = str(first_row.get(req.mapping.get("patent_no", ""), "")) or f"row_0"
    doc = zvec.Doc(
        id=patent_no,
        vectors={"embedding": first_embeddings[0]},
        fields={
            "patent_no": patent_no,
            "applicant": str(first_row.get(req.mapping.get("applicant"), "")),
            "title": str(first_row.get(req.mapping.get("title"), "")),
            "abstract": str(first_row.get(req.mapping.get("abstract"), "")),
            "claims": str(first_row.get(req.mapping.get("claims"), "")),
        },
    )
    try:
        collection.insert(doc)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"插入数据失败: {e}")

    imported = 1
    failed = 0

    # 6. 批量处理剩余数据
    remaining_rows = rows[1:]
    total = len(rows)

    # 收集待处理的文本和行索引
    batch_texts: list[str] = []
    batch_indices: list[int] = []

    for i, row in enumerate(remaining_rows, start=1):
        text = _build_text(row, req.mapping)
        if not text.strip():
            failed += 1
            continue
        batch_texts.append(text)
        batch_indices.append(i)

        # 达到 embedding 批量大小时调用接口
        if len(batch_texts) >= EMBEDDING_BATCH_SIZE:
            try:
                embeddings = _generate_embeddings(batch_texts, api_key, model_name, base_url)
            except Exception as e:
                # 嵌入接口失败，返回已导入的数量
                return ImportResponse(
                    total=total,
                    imported=imported,
                    failed=failed + len(batch_texts),
                    error=f"调用嵌入接口失败: {e}",
                )

            # 构建文档并插入
            docs = []
            for idx_in_batch, row_idx in enumerate(batch_indices):
                row = remaining_rows[row_idx - 1]
                p_no = str(row.get(req.mapping.get("patent_no", ""), "")) or f"row_{row_idx}"
                docs.append(zvec.Doc(
                    id=p_no,
                    vectors={"embedding": embeddings[idx_in_batch]},
                    fields={
                        "patent_no": p_no,
                        "applicant": str(row.get(req.mapping.get("applicant"), "")),
                        "title": str(row.get(req.mapping.get("title"), "")),
                        "abstract": str(row.get(req.mapping.get("abstract"), "")),
                        "claims": str(row.get(req.mapping.get("claims"), "")),
                    },
                ))

            # 分批插入
            for j in range(0, len(docs), INSERT_BATCH_SIZE):
                batch_docs = docs[j:j + INSERT_BATCH_SIZE]
                try:
                    collection.insert(batch_docs)
                    imported += len(batch_docs)
                except Exception as e:
                    failed += len(batch_docs)
                    return ImportResponse(
                        total=total,
                        imported=imported,
                        failed=failed,
                        error=f"插入数据失败: {e}",
                    )

            batch_texts = []
            batch_indices = []

    # 处理剩余不足一批的文本
    if batch_texts:
        try:
            embeddings = _generate_embeddings(batch_texts, api_key, model_name, base_url)
        except Exception as e:
            return ImportResponse(
                total=total,
                imported=imported,
                failed=failed + len(batch_texts),
                error=f"调用嵌入接口失败: {e}",
            )

        docs = []
        for idx_in_batch, row_idx in enumerate(batch_indices):
            row = remaining_rows[row_idx - 1]
            p_no = str(row.get(req.mapping.get("patent_no", ""), "")) or f"row_{row_idx}"
            docs.append(zvec.Doc(
                id=p_no,
                vectors={"embedding": embeddings[idx_in_batch]},
                fields={
                    "patent_no": p_no,
                    "applicant": str(row.get(req.mapping.get("applicant"), "")),
                    "title": str(row.get(req.mapping.get("title"), "")),
                    "abstract": str(row.get(req.mapping.get("abstract"), "")),
                    "claims": str(row.get(req.mapping.get("claims"), "")),
                },
            ))

        for j in range(0, len(docs), INSERT_BATCH_SIZE):
            batch_docs = docs[j:j + INSERT_BATCH_SIZE]
            try:
                collection.insert(batch_docs)
                imported += len(batch_docs)
            except Exception as e:
                failed += len(batch_docs)
                return ImportResponse(
                    total=total,
                    imported=imported,
                    failed=failed,
                    error=f"插入数据失败: {e}",
                )

    return ImportResponse(total=total, imported=imported, failed=failed)


@router.get("/status", response_model=StatusResponse)
def get_status():
    """获取集合状态"""
    collection = get_collection()
    if collection is None:
        return StatusResponse(collection_exists=False, document_count=0, dimension=None)

    doc_count = collection.stats.doc_count
    # 从 schema 中获取向量维度
    dimension = None
    vectors = collection.schema.vectors
    if vectors:
        dimension = vectors[0].dimension

    return StatusResponse(
        collection_exists=True,
        document_count=doc_count,
        dimension=dimension,
    )
