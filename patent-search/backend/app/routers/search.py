"""语义搜索路由"""
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
DEFAULT_MODEL_NAME = "text-embedding-v3"
DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


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


def _get_embedding(text: str) -> list[float]:
    """调用嵌入 API 将文本转为向量"""
    config = _read_config()
    api_key = config.get("api_key", "")
    model_name = config.get("model_name", DEFAULT_MODEL_NAME)
    base_url = config.get("base_url", DEFAULT_BASE_URL)

    if not api_key:
        raise HTTPException(status_code=400, detail="API 密钥为空，请先配置")

    client = OpenAI(api_key=api_key, base_url=base_url)
    response = client.embeddings.create(model=model_name, input=text)
    return response.data[0].embedding


@router.post("", response_model=SearchResponse)
async def search(req: SearchRequest):
    """语义搜索专利"""
    # 检查数据库是否存在
    if not DB_PATH.exists():
        raise HTTPException(status_code=404, detail="请先导入数据")

    # 获取查询向量
    query_vector = _get_embedding(req.query)

    # 打开集合
    try:
        collection = zvec.open(str(DB_PATH))
    except Exception:
        raise HTTPException(status_code=404, detail="请先导入数据")

    # 构建查询
    query_obj = zvec.Query(field_name="embedding", vector=query_vector)

    # 构建过滤条件
    filter_expr = None
    if req.applicant:
        filter_expr = f"applicant == '{req.applicant}'"

    # 执行查询
    try:
        results = collection.query(
            queries=query_obj,
            topk=req.topk,
            filter=filter_expr,
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
            claims=str(fields.get("claims", "")),
        ))

    return SearchResponse(results=hits)


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
