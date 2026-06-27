"""语义搜索路由（三向量加权检索，支持自定义权重和字段开关）"""
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from openai import OpenAI
from pydantic import BaseModel, Field
import zvec

router = APIRouter(prefix="/api/search", tags=["搜索"])

# 路径常量
DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
CONFIG_FILE = DATA_DIR / "config.json"
DB_PATH = DATA_DIR / "patent_db"

# 默认配置值
DEFAULT_MODEL_NAME = "Qwen/Qwen3-Embedding-0.6B"
DEFAULT_BASE_URL = "https://api.siliconflow.cn/v1"

# 向量维度（与导入保持一致）
VECTOR_DIMENSION = 512

# 默认加权系数（权利要求和摘要最重，说明书次要）
DEFAULT_TITLE_ABS_WEIGHT = 0.45
DEFAULT_DESC_WEIGHT = 0.15
DEFAULT_CLAIMS_WEIGHT = 0.40

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
    # 自定义权重（仅在开关开启时生效）
    weight_title_abs: float = Field(default=DEFAULT_TITLE_ABS_WEIGHT, description="标题+摘要权重")
    weight_desc: float = Field(default=DEFAULT_DESC_WEIGHT, description="说明书权重")
    weight_claims: float = Field(default=DEFAULT_CLAIMS_WEIGHT, description="权利要求权重")


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

    client = OpenAI(api_key=api_key, base_url=base_url)
    response = client.embeddings.create(
        model=model_name,
        input=input_text,
        dimensions=VECTOR_DIMENSION,
    )
    return response.data[0].embedding


def _normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    """归一化权重，使总和为 1"""
    total = sum(weights.values())
    if total <= 0:
        # 如果全为 0，均分
        n = len(weights)
        return {k: 1.0 / n for k in weights} if n > 0 else weights
    return {k: v / total for k, v in weights.items()}


@router.post("", response_model=SearchResponse)
async def search(req: SearchRequest):
    """语义搜索专利（三向量加权检索，支持自定义权重和字段开关）"""
    if not DB_PATH.exists():
        raise HTTPException(status_code=404, detail="请先导入数据")

    # 构建启用的向量字段列表及其权重
    enabled_fields: dict[str, dict] = {}
    if req.use_title_abs:
        enabled_fields["title_abs"] = {"weight": req.weight_title_abs, **VECTOR_FIELDS["title_abs"]}
    if req.use_desc:
        enabled_fields["desc"] = {"weight": req.weight_desc, **VECTOR_FIELDS["desc"]}
    if req.use_claims:
        enabled_fields["claims"] = {"weight": req.weight_claims, **VECTOR_FIELDS["claims"]}

    if not enabled_fields:
        raise HTTPException(status_code=400, detail="请至少启用一个向量字段")

    # 归一化权重
    raw_weights = {k: v["weight"] for k, v in enabled_fields.items()}
    norm_weights = _normalize_weights(raw_weights)

    # 为每个启用的字段生成查询向量
    query_vectors: dict[str, list[float]] = {}
    for key, cfg in enabled_fields.items():
        query_vectors[key] = _get_embedding(req.query, instruction=cfg["instruction"])

    # 打开集合
    try:
        collection = zvec.open(str(DB_PATH))
    except Exception:
        raise HTTPException(status_code=404, detail="请先导入数据")

    # 构建过滤条件
    filter_expr = None
    if req.applicant:
        filter_expr = f"applicant == '{req.applicant}'"

    candidate_count = min(req.topk * 3, 100)

    # 对每个启用的字段执行查询
    field_results: dict[str, list] = {}
    for key, cfg in enabled_fields.items():
        try:
            results = collection.query(
                queries=zvec.Query(field_name=cfg["field_name"], vector=query_vectors[key]),
                topk=candidate_count,
                filter=filter_expr,
            )
            field_results[key] = results
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"搜索{cfg['label']}向量失败: {e}")

    # 合并结果，使用加权分数
    score_map: dict[str, dict] = {}

    for key, docs in field_results.items():
        for doc in docs:
            score_key = f"{key}_score"
            if doc.id not in score_map:
                score_map[doc.id] = {"id": doc.id, "fields": doc.fields or {}}
                # 初始化所有字段分数为 0
                for k in enabled_fields:
                    score_map[doc.id][f"{k}_score"] = 0.0
            score_map[doc.id][score_key] = doc.score if doc.score is not None else 0.0

    # 计算加权最终分数
    merged = []
    for doc_id, info in score_map.items():
        final_score = 0.0
        for key in enabled_fields:
            final_score += norm_weights[key] * info.get(f"{key}_score", 0.0)
        fields = info["fields"]
        merged.append(SearchHit(
            id=doc_id,
            score=final_score,
            patent_no=str(fields.get("patent_no", "")),
            applicant=str(fields.get("applicant", "")),
            title=str(fields.get("title", "")),
            abstract=str(fields.get("abstract", "")),
            description=str(fields.get("description", "")),
            claims=str(fields.get("claims", "")),
        ))

    merged.sort(key=lambda x: x.score, reverse=True)
    return SearchResponse(results=merged[:req.topk])


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
