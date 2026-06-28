"""语义搜索路由（混合检索：密集向量 + BM25稀疏向量，使用 multi_query + WeightedReRanker）"""
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from openai import OpenAI
from pydantic import BaseModel, Field
import zvec
from zvec import Query

router = APIRouter(prefix="/api/search", tags=["搜索"])

# 路径常量
DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
CONFIG_FILE = DATA_DIR / "config.json"
DB_PATH = DATA_DIR / "patent_db"

# 默认配置值
DEFAULT_MODEL_NAME = "embedding-3"
DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
DEFAULT_DIMENSION = 512

# 默认加权系数（标题摘要和权利要求最重，BM25关键词次之，说明书辅助）
DEFAULT_TITLE_ABS_WEIGHT = 0.40
DEFAULT_DESC_WEIGHT = 0.10
DEFAULT_CLAIMS_WEIGHT = 0.30
DEFAULT_BM25_WEIGHT = 0.20

# 查询指令前缀
TITLE_ABS_INSTRUCTION = "Retrieve the most relevant patents"
DESC_INSTRUCTION = "Find patents with similar technical details and implementation"
CLAIMS_INSTRUCTION = "Find patents with similar claim scope"

# 向量字段配置
VECTOR_FIELDS = {
    "title_abs": {
        "field_name": "title_abs_vec",
        "instruction": TITLE_ABS_INSTRUCTION,
        "default_weight": DEFAULT_TITLE_ABS_WEIGHT,
        "label": "标题+摘要",
    },
    "desc": {
        "field_name": "desc_vec",
        "instruction": DESC_INSTRUCTION,
        "default_weight": DEFAULT_DESC_WEIGHT,
        "label": "说明书",
    },
    "claims": {
        "field_name": "claims_vec",
        "instruction": CLAIMS_INSTRUCTION,
        "default_weight": DEFAULT_CLAIMS_WEIGHT,
        "label": "权利要求",
    },
    "bm25": {
        "field_name": "bm25_vec",
        "default_weight": DEFAULT_BM25_WEIGHT,
        "label": "关键词(BM25)",
    },
}


class SearchRequest(BaseModel):
    """搜索请求模型"""
    query: str = Field(..., description="搜索查询文本")
    applicant: str | None = Field(default=None, description="申请人过滤条件")
    topk: int = Field(default=10, description="返回结果数量")
    # 向量字段开关
    use_title_abs: bool = Field(default=True, description="是否使用标题+摘要向量")
    use_desc: bool = Field(default=True, description="是否使用说明书向量")
    use_claims: bool = Field(default=True, description="是否使用权利要求向量")
    use_bm25: bool = Field(default=True, description="是否使用BM25关键词向量")
    # 自定义权重（仅在开关开启时生效）
    weight_title_abs: float = Field(default=DEFAULT_TITLE_ABS_WEIGHT, description="标题+摘要权重")
    weight_desc: float = Field(default=DEFAULT_DESC_WEIGHT, description="说明书权重")
    weight_claims: float = Field(default=DEFAULT_CLAIMS_WEIGHT, description="权利要求权重")
    weight_bm25: float = Field(default=DEFAULT_BM25_WEIGHT, description="BM25关键词权重")


class SearchHit(BaseModel):
    """单条搜索结果"""
    id: str
    score: float
    patent_no: str = ""
    applicant: str = ""
    title: str = ""
    abstract: str = ""
    description: str = ""
    claims: str = ""


class SearchResponse(BaseModel):
    """搜索响应模型"""
    results: list[SearchHit]


class VectorFieldConfig(BaseModel):
    """向量字段配置（用于前端渲染）"""
    key: str
    label: str
    enabled: bool
    weight: float


class StatusResponse(BaseModel):
    """搜索状态响应"""
    available: bool
    document_count: int
    vector_fields: list[VectorFieldConfig] = []


def _read_config() -> dict:
    """读取配置文件"""
    if not CONFIG_FILE.exists():
        raise HTTPException(status_code=400, detail="请先配置 API 密钥")
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _get_embedding(text: str, instruction: str | None = None) -> list[float]:
    """调用嵌入 API 将文本转为向量"""
    config = _read_config()
    api_key = config.get("api_key", "")
    model_name = config.get("model_name", DEFAULT_MODEL_NAME)
    base_url = config.get("base_url", DEFAULT_BASE_URL)

    if not api_key:
        raise HTTPException(status_code=400, detail="API 密钥为空，请先配置")

    if instruction:
        input_text = f"Instruct: {instruction}\nQuery: {text}"
    else:
        input_text = text

    dimension = config.get("dimension", DEFAULT_DIMENSION)

    client = OpenAI(api_key=api_key, base_url=base_url)
    response = client.embeddings.create(
        model=model_name,
        input=input_text,
        dimensions=dimension,
    )
    return response.data[0].embedding


def _normalize_weights(weights: list[float]) -> list[float]:
    """归一化权重列表，使总和为 1"""
    total = sum(weights)
    if total <= 0:
        n = len(weights)
        return [1.0 / n for _ in weights] if n > 0 else weights
    return [w / total for w in weights]


# BM25 查询向量生成器（延迟初始化）
_bm25_query_fn = None


def _get_bm25_query_fn():
    """获取 BM25 查询编码器（延迟初始化）"""
    global _bm25_query_fn
    if _bm25_query_fn is None:
        try:
            from zvec.extension import BM25EmbeddingFunction
            _bm25_query_fn = BM25EmbeddingFunction(language="zh", encoding_type="query")
        except ImportError:
            pass  # dashtext 未安装时跳过 BM25
    return _bm25_query_fn


@router.post("", response_model=SearchResponse)
async def search(req: SearchRequest):
    """混合检索专利（密集向量 + BM25稀疏向量，使用 multi_query + WeightedReRanker）"""
    if not DB_PATH.exists():
        raise HTTPException(status_code=404, detail="请先导入数据")

    # 构建 queries 列表和对应权重
    queries: list[Query] = []
    weights: list[float] = []

    if req.use_title_abs:
        title_abs_vec = _get_embedding(req.query, instruction=TITLE_ABS_INSTRUCTION)
        queries.append(Query(field_name="title_abs_vec", vector=title_abs_vec))
        weights.append(req.weight_title_abs)

    if req.use_desc:
        desc_vec = _get_embedding(req.query, instruction=DESC_INSTRUCTION)
        queries.append(Query(field_name="desc_vec", vector=desc_vec))
        weights.append(req.weight_desc)

    if req.use_claims:
        claims_vec = _get_embedding(req.query, instruction=CLAIMS_INSTRUCTION)
        queries.append(Query(field_name="claims_vec", vector=claims_vec))
        weights.append(req.weight_claims)

    if req.use_bm25:
        bm25_fn = _get_bm25_query_fn()
        if bm25_fn is not None:
            bm25_vec = bm25_fn.embed(req.query)
            queries.append(Query(field_name="bm25_vec", vector=bm25_vec))
            weights.append(req.weight_bm25)

    if not queries:
        raise HTTPException(status_code=400, detail="请至少启用一个向量字段")

    # 归一化权重
    norm_weights = _normalize_weights(weights)

    # 打开集合
    try:
        collection = zvec.open(str(DB_PATH))
    except Exception:
        raise HTTPException(status_code=404, detail="请先导入数据")

    # 构建过滤条件
    filter_expr = None
    if req.applicant:
        filter_expr = f"applicant == '{req.applicant}'"

    # 使用 multi_query + WeightedReRanker 执行混合检索
    try:
        from zvec.extension import WeightedReRanker
        results = collection.query(
            queries=queries,
            topk=req.topk,
            filter=filter_expr,
            reranker=WeightedReRanker(norm_weights),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"搜索失败: {e}")

    # 转换结果
    hits = []
    for doc in results:
        fields = doc.fields or {}
        hits.append(SearchHit(
            id=doc.id,
            score=doc.score if doc.score is not None else 0.0,
            patent_no=str(fields.get("patent_no", "")),
            applicant=str(fields.get("applicant", "")),
            title=str(fields.get("title", "")),
            abstract=str(fields.get("abstract", "")),
            description=str(fields.get("description", "")),
            claims=str(fields.get("claims", "")),
        ))

    return SearchResponse(results=hits)


@router.get("/status", response_model=StatusResponse)
async def search_status():
    """检查搜索功能是否可用，返回向量字段默认配置"""
    if not DB_PATH.exists():
        return StatusResponse(
            available=False,
            document_count=0,
            vector_fields=[
                VectorFieldConfig(
                    key=k, label=v["label"], enabled=True, weight=v["default_weight"],
                )
                for k, v in VECTOR_FIELDS.items()
            ],
        )

    try:
        collection = zvec.open(str(DB_PATH))
        stats = collection.stats
        doc_count = stats.doc_count
        return StatusResponse(
            available=True,
            document_count=doc_count,
            vector_fields=[
                VectorFieldConfig(
                    key=k, label=v["label"], enabled=True, weight=v["default_weight"],
                )
                for k, v in VECTOR_FIELDS.items()
            ],
        )
    except Exception:
        return StatusResponse(available=False, document_count=0)
