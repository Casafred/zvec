"""数据导入路由（三向量 + BM25稀疏向量：标题摘要 + 说明书 + 权利要求 + 关键词）"""
import json
import re
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

# BM25 稀疏向量生成器（延迟初始化，避免 dashtext 不兼容时整个模块无法导入）
_bm25_doc_fn = None


def _get_bm25_doc_fn():
    """获取 BM25 文档编码器（延迟初始化）"""
    global _bm25_doc_fn
    if _bm25_doc_fn is None:
        try:
            from zvec.extension import BM25EmbeddingFunction
            _bm25_doc_fn = BM25EmbeddingFunction(language="zh", encoding_type="document")
        except ImportError:
            pass  # dashtext 未安装时跳过 BM25
    return _bm25_doc_fn


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


def _extract_first_claim(claims_text: str) -> str:
    """智能提取第一条独立权利要求

    优先匹配 "1." / "1．" / "权利要求1" 等标记，
    截取到 "2." / "2．" 标记为止；若无明确标记则取前 8000 字符。
    """
    if not claims_text:
        return ""

    # 尝试匹配以 "1." / "1．" / "权利要求1" 开头的首条权利要求
    first_claim_pattern = re.compile(
        r'(?:^|\n)\s*(?:1[.．]|权利要求\s*1[.．、:]?\s*)',
        re.IGNORECASE,
    )
    match = first_claim_pattern.search(claims_text)
    if match:
        # 从匹配位置开始提取
        start = match.start()
        # 寻找第二条权利要求的起始位置
        second_claim_pattern = re.compile(
            r'(?:^|\n)\s*2[.．]',
            re.IGNORECASE,
        )
        second_match = second_claim_pattern.search(claims_text, match.end())
        if second_match:
            return claims_text[start:second_match.start()].strip()
        else:
            # 没有找到第二条，取从匹配位置到末尾（不超过 8000 字符）
            return claims_text[start:start + 8000].strip()

    # 无明确标记，取前 8000 字符
    return claims_text[:8000].strip()


def build_title_abs_text(row: dict, mapping: dict[str, str | None]) -> str:
    """构建标题+摘要文本（用于 title_abs_vec）"""
    parts = []
    for field_key in ("title", "abstract"):
        col_name = mapping.get(field_key)
        if col_name and col_name in row:
            value = str(row[col_name]).strip()
            if value:
                parts.append(value)
    return "\n".join(parts)


# 说明书关键章节正则
_DESC_SECTION_PATTERN = re.compile(
    r'(?:技术领域|背景技术|发明内容|具体实施方式|实施例)',
    re.IGNORECASE,
)


def _extract_desc_key_sections(desc_text: str, max_chars: int = 16000) -> str:
    """智能提取说明书关键章节

    策略：
    1. 优先提取"发明内容"章节（通常包含技术方案核心）
    2. 若无明确章节标记，取前 max_chars 字符
    3. 总长度不超过 max_chars（约 8000 token，留足 32K 上限余量）
    """
    if not desc_text:
        return ""

    # 尝试提取"发明内容"章节：从"发明内容"到下一个章节标题
    invention_pattern = re.compile(
        r'发明内容[：:\s]*\n?(.*?)(?=(?:技术领域|背景技术|附图说明|具体实施方式|实施例|权利要求|$))',
        re.IGNORECASE | re.DOTALL,
    )
    invention_match = invention_pattern.search(desc_text)
    invention_section = invention_match.group(1).strip() if invention_match else ""

    # 尝试提取"具体实施方式"的前部分
    impl_pattern = re.compile(
        r'具体实施方式[：:\s]*\n?(.*?)(?=(?:附图说明|权利要求|$))',
        re.IGNORECASE | re.DOTALL,
    )
    impl_match = impl_pattern.search(desc_text)
    impl_section = ""
    if impl_match:
        # 具体实施方式可能极长，只取前 8000 字符
        impl_section = impl_match.group(1).strip()[:8000]

    # 组合：发明内容 + 具体实施方式（前部分）
    if invention_section and impl_section:
        combined = f"发明内容：\n{invention_section}\n\n具体实施方式：\n{impl_section}"
    elif invention_section:
        combined = f"发明内容：\n{invention_section}"
    elif impl_section:
        combined = f"具体实施方式：\n{impl_section}"
    else:
        # 无明确章节标记，取前 max_chars 字符
        combined = desc_text[:max_chars].strip()

    # 最终截断保护
    return combined[:max_chars]


def build_desc_text(row: dict, mapping: dict[str, str | None]) -> str:
    """构建说明书文本（用于 desc_vec），提取关键章节"""
    col_name = mapping.get("description")
    if col_name and col_name in row:
        desc = str(row[col_name]).strip()
        if desc:
            return _extract_desc_key_sections(desc)
    return ""


def build_claims_text(row: dict, mapping: dict[str, str | None]) -> str:
    """构建权利要求文本（用于 claims_vec），仅取首条独立权利要求"""
    col_name = mapping.get("claims")
    if col_name and col_name in row:
        claims = str(row[col_name]).strip()
        if claims:
            return _extract_first_claim(claims)
    return ""


def build_bm25_text(row: dict, mapping: dict[str, str | None]) -> str:
    """构建 BM25 文本（标题 + 摘要 + 首条权利要求），用于生成稀疏向量"""
    parts = []
    # 标题
    col_name = mapping.get("title")
    if col_name and col_name in row:
        value = str(row[col_name]).strip()
        if value:
            parts.append(value)
    # 摘要
    col_name = mapping.get("abstract")
    if col_name and col_name in row:
        value = str(row[col_name]).strip()
        if value:
            parts.append(value)
    # 首条权利要求
    claims_text = build_claims_text(row, mapping)
    if claims_text:
        parts.append(claims_text)
    return "\n".join(parts)


def _generate_embeddings(
    texts: list[str],
    api_key: str,
    model_name: str,
    base_url: str,
    dimensions: int = 512,
) -> list[list[float]]:
    """调用 OpenAI 兼容接口生成向量，支持指定维度"""
    client = OpenAI(api_key=api_key, base_url=base_url)
    response = client.embeddings.create(
        model=model_name,
        input=texts,
        dimensions=dimensions,
    )
    # 按 index 排序确保顺序一致
    sorted_data = sorted(response.data, key=lambda x: x.index)
    return [item.embedding for item in sorted_data]


def _build_doc(row: dict, mapping: dict[str, str | None], row_idx: int,
               title_abs_vec: list[float], desc_vec: list[float], claims_vec: list[float],
               bm25_vec: dict[int, float]) -> zvec.Doc:
    """构建单条文档（含 BM25 稀疏向量）"""
    p_no = str(row.get(mapping.get("patent_no", ""), "")) or f"row_{row_idx}"
    return zvec.Doc(
        id=p_no,
        vectors={
            "title_abs_vec": title_abs_vec,
            "desc_vec": desc_vec,
            "claims_vec": claims_vec,
            "bm25_vec": bm25_vec,
        },
        fields={
            "patent_no": p_no,
            "applicant": str(row.get(mapping.get("applicant"), "")),
            "title": str(row.get(mapping.get("title"), "")),
            "abstract": str(row.get(mapping.get("abstract"), "")),
            "description": str(row.get(mapping.get("description"), "")),
            "claims": str(row.get(mapping.get("claims"), "")),
        },
    )


@router.post("", response_model=ImportResponse)
def import_data(req: ImportRequest):
    """从已上传的 Excel 文件导入数据到向量集合（三向量策略）"""
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
    model_name = config.get("model_name", "embedding-3")
    base_url = config.get("base_url", "https://open.bigmodel.cn/api/paas/v4")
    dimension = config.get("dimension", 512)

    if not api_key:
        raise HTTPException(status_code=400, detail="API 密钥为空，请先在设置页面配置")

    # 3. 用第一条数据探测 API 连通性
    first_title_abs = build_title_abs_text(rows[0], req.mapping)
    if not first_title_abs.strip():
        raise HTTPException(status_code=400, detail="第一条数据的标题+摘要为空，请检查映射关系")

    try:
        first_title_abs_emb = _generate_embeddings(
            [first_title_abs], api_key, model_name, base_url, dimensions=dimension,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"调用嵌入接口失败: {e}")

    # 4. 获取或创建集合（固定 512 维）
    collection = get_or_create_collection(dimension)

    # 5. 生成第一条数据的 desc 和 claims 向量并插入
    zero_vec = [0.0] * dimension

    first_desc = build_desc_text(rows[0], req.mapping)
    if first_desc.strip():
        try:
            first_desc_emb = _generate_embeddings(
                [first_desc], api_key, model_name, base_url, dimensions=dimension,
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"调用嵌入接口失败: {e}")
    else:
        first_desc_emb = [zero_vec]

    first_claims = build_claims_text(rows[0], req.mapping)
    if first_claims.strip():
        try:
            first_claims_emb = _generate_embeddings(
                [first_claims], api_key, model_name, base_url, dimensions=dimension,
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"调用嵌入接口失败: {e}")
    else:
        first_claims_emb = [zero_vec]

    # BM25 稀疏向量
    bm25_fn = _get_bm25_doc_fn()
    first_bm25_vec = bm25_fn.embed(build_bm25_text(rows[0], req.mapping)) if bm25_fn else {}

    first_doc = _build_doc(
        rows[0], req.mapping, 0,
        first_title_abs_emb[0], first_desc_emb[0], first_claims_emb[0],
        first_bm25_vec,
    )
    try:
        collection.insert(first_doc)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"插入数据失败: {e}")

    imported = 1
    failed = 0

    # 6. 批量处理剩余数据
    remaining_rows = rows[1:]
    total = len(rows)
    bm25_fn = _get_bm25_doc_fn()  # 缓存，避免循环中重复初始化

    # 收集待处理的文本和行索引
    batch_title_abs: list[str] = []
    batch_desc: list[str] = []
    batch_claims: list[str] = []
    batch_bm25: list[str] = []
    batch_indices: list[int] = []

    def _embed_with_zero_fallback(texts: list[str], api_key: str, model_name: str, base_url: str) -> list[list[float]]:
        """对非空文本生成向量，空文本用零向量填充"""
        non_empty = [t for t in texts if t]
        if not non_empty:
            return [zero_vec] * len(texts)
        raw = _generate_embeddings(non_empty, api_key, model_name, base_url, dimensions=dimension)
        result = []
        raw_idx = 0
        for t in texts:
            if t:
                result.append(raw[raw_idx])
                raw_idx += 1
            else:
                result.append(zero_vec)
        return result

    for i, row in enumerate(remaining_rows, start=1):
        title_abs = build_title_abs_text(row, req.mapping)
        desc = build_desc_text(row, req.mapping)
        claims = build_claims_text(row, req.mapping)
        bm25_text = build_bm25_text(row, req.mapping)

        # 标题+摘要为空则跳过
        if not title_abs.strip():
            failed += 1
            continue

        batch_title_abs.append(title_abs)
        batch_desc.append(desc if desc.strip() else "")
        batch_claims.append(claims if claims.strip() else "")
        batch_bm25.append(bm25_text)
        batch_indices.append(i)

        # 达到 embedding 批量大小时调用接口
        if len(batch_title_abs) >= EMBEDDING_BATCH_SIZE:
            try:
                title_abs_embeddings = _generate_embeddings(
                    batch_title_abs, api_key, model_name, base_url, dimensions=dimension,
                )
                desc_embeddings = _embed_with_zero_fallback(
                    batch_desc, api_key, model_name, base_url,
                )
                claims_embeddings = _embed_with_zero_fallback(
                    batch_claims, api_key, model_name, base_url,
                )
            except Exception as e:
                return ImportResponse(
                    total=total,
                    imported=imported,
                    failed=failed + len(batch_title_abs),
                    error=f"调用嵌入接口失败: {e}",
                )

            # 构建文档并插入
            docs = []
            for idx_in_batch, row_idx in enumerate(batch_indices):
                row = remaining_rows[row_idx - 1]
                bm25_vec = bm25_fn.embed(batch_bm25[idx_in_batch]) if bm25_fn else {}
                docs.append(_build_doc(
                    row, req.mapping, row_idx,
                    title_abs_embeddings[idx_in_batch],
                    desc_embeddings[idx_in_batch],
                    claims_embeddings[idx_in_batch],
                    bm25_vec,
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

            batch_title_abs = []
            batch_desc = []
            batch_claims = []
            batch_bm25 = []
            batch_indices = []

    # 处理剩余不足一批的文本
    if batch_title_abs:
        try:
            title_abs_embeddings = _generate_embeddings(
                batch_title_abs, api_key, model_name, base_url, dimensions=dimension,
            )
            desc_embeddings = _embed_with_zero_fallback(
                batch_desc, api_key, model_name, base_url,
            )
            claims_embeddings = _embed_with_zero_fallback(
                batch_claims, api_key, model_name, base_url,
            )
        except Exception as e:
            return ImportResponse(
                total=total,
                imported=imported,
                failed=failed + len(batch_title_abs),
                error=f"调用嵌入接口失败: {e}",
            )

        docs = []
        for idx_in_batch, row_idx in enumerate(batch_indices):
            row = remaining_rows[row_idx - 1]
            bm25_vec = bm25_fn.embed(batch_bm25[idx_in_batch]) if bm25_fn else {}
            docs.append(_build_doc(
                row, req.mapping, row_idx,
                title_abs_embeddings[idx_in_batch],
                desc_embeddings[idx_in_batch],
                claims_embeddings[idx_in_batch],
                bm25_vec,
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
    # 从 schema 中获取向量维度（取第一个向量字段的维度）
    dimension = None
    vectors = collection.schema.vectors
    if vectors:
        dimension = vectors[0].dimension

    return StatusResponse(
        collection_exists=True,
        document_count=doc_count,
        dimension=dimension,
    )
