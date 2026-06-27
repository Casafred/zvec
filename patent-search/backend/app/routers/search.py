"""语义搜索路由（三向量加权检索）"""
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

# 三向量加权系数
TITLE_ABS_WEIGHT = 0.4
DESC_WEIGHT = 0.35
CLAIMS_WEIGHT = 0.25

# 查询指令前缀
TITLE_ABS_INSTRUCTION = "Retrieve the most relevant patents"
DESC_INSTRUCTION = "Find patents with similar technical details and implementation"
CLAIMS_INSTRUCTION = "Find patents with similar claim scope"


class SearchRequest(BaseModel):
    """搜索请求模型"""
    query: str = Field(..., description="搜索查询文本")
    applicant: str | None = Field(default=None, description="申请人过滤条件")
    topk: int = Field(default=10, description="返回结果数量")


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


class StatusResponse(BaseModel):
    """搜索状态响应"""
    available: bool
    document_count: int


def _read_config() -> dict:
    """读取配置文件"""
    if not CONFIG_FILE.exists():
        raise HTTPException(status_code=400, detail="请先配置 API 密钥")
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _get_embedding(text: str, instruction: str | None = None) -> list[float]:
    """调用嵌入 API 将文本转为向量

    如果提供 instruction，则格式化为 "Instruct: {instruction}\\nQuery: {text}"；
    否则直接使用 text 作为输入（用于文档侧嵌入）。
    """
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


@router.post("", response_model=SearchResponse)
async def search(req: SearchRequest):
    """语义搜索专利（三向量加权检索）"""
    # 检查数据库是否存在
    if not DB_PATH.exists():
        raise HTTPException(status_code=404, detail="请先导入数据")

    # 生成三组查询向量（带不同指令前缀）
    title_abs_query_vec = _get_embedding(req.query, instruction=TITLE_ABS_INSTRUCTION)
    desc_query_vec = _get_embedding(req.query, instruction=DESC_INSTRUCTION)
    claims_query_vec = _get_embedding(req.query, instruction=CLAIMS_INSTRUCTION)

    # 打开集合
    try:
        collection = zvec.open(str(DB_PATH))
    except Exception:
        raise HTTPException(status_code=404, detail="请先导入数据")

    # 构建过滤条件
    filter_expr = None
    if req.applicant:
        filter_expr = f"applicant == '{req.applicant}'"

    # 分别对三个向量字段执行查询，取更多候选以便融合排序
    candidate_count = min(req.topk * 3, 100)

    try:
        title_abs_results = collection.query(
            queries=zvec.Query(field_name="title_abs_vec", vector=title_abs_query_vec),
            topk=candidate_count,
            filter=filter_expr,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"搜索标题摘要向量失败: {e}")

    try:
        desc_results = collection.query(
            queries=zvec.Query(field_name="desc_vec", vector=desc_query_vec),
            topk=candidate_count,
            filter=filter_expr,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"搜索说明书向量失败: {e}")

    try:
        claims_results = collection.query(
            queries=zvec.Query(field_name="claims_vec", vector=claims_query_vec),
            topk=candidate_count,
            filter=filter_expr,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"搜索权利要求向量失败: {e}")

    # 合并三组结果，使用加权分数
    score_map: dict[str, dict] = {}

    for doc in title_abs_results:
        score_map[doc.id] = {
            "id": doc.id,
            "title_abs_score": doc.score if doc.score is not None else 0.0,
            "desc_score": 0.0,
            "claims_score": 0.0,
            "fields": doc.fields or {},
        }

    for doc in desc_results:
        if doc.id in score_map:
            score_map[doc.id]["desc_score"] = doc.score if doc.score is not None else 0.0
        else:
            score_map[doc.id] = {
                "id": doc.id,
                "title_abs_score": 0.0,
                "desc_score": doc.score if doc.score is not None else 0.0,
                "claims_score": 0.0,
                "fields": doc.fields or {},
            }

    for doc in claims_results:
        if doc.id in score_map:
            score_map[doc.id]["claims_score"] = doc.score if doc.score is not None else 0.0
        else:
            score_map[doc.id] = {
                "id": doc.id,
                "title_abs_score": 0.0,
                "desc_score": 0.0,
                "claims_score": doc.score if doc.score is not None else 0.0,
                "fields": doc.fields or {},
            }

    # 计算加权最终分数并排序
    merged = []
    for doc_id, info in score_map.items():
        final_score = (
            TITLE_ABS_WEIGHT * info["title_abs_score"]
            + DESC_WEIGHT * info["desc_score"]
            + CLAIMS_WEIGHT * info["claims_score"]
        )
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
    """检查搜索功能是否可用"""
    if not DB_PATH.exists():
        return StatusResponse(available=False, document_count=0)

    try:
        collection = zvec.open(str(DB_PATH))
        stats = collection.stats
        doc_count = stats.doc_count
        return StatusResponse(available=True, document_count=doc_count)
    except Exception:
        return StatusResponse(available=False, document_count=0)
