"""文件上传路由（支持 multipart 和 base64 JSON 两种方式）"""
import base64
import io
import json
import uuid
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/upload", tags=["上传"])

UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "uploaded"

# 专利字段到中文名的映射规则
MAPPING_RULES: dict[str, list[str]] = {
    "patent_no": ["专利号", "申请号", "专利申请号"],
    "applicant": ["专利申请人", "申请人", "申请者"],
    "title": ["标题", "专利名称", "发明名称", "专利标题"],
    "abstract": ["摘要", "专利摘要", "发明摘要"],
    "description": ["说明书", "专利说明书", "发明说明书", "详细说明", "说明"],
    "claims": ["权利要求", "权利要求书", "要求"],
}


def auto_detect_mapping(columns: list[str]) -> dict[str, str | None]:
    """根据列名自动检测映射关系"""
    mapping: dict[str, str | None] = {}
    used_columns: set[str] = set()

    for field, candidates in MAPPING_RULES.items():
        matched = None
        for candidate in candidates:
            if candidate in columns and candidate not in used_columns:
                matched = candidate
                break
        if matched:
            mapping[field] = matched
            used_columns.add(matched)
        else:
            mapping[field] = None

    return mapping


def _parse_excel_and_save(contents: bytes, filename: str) -> dict:
    """解析 Excel 并保存为临时 JSON，返回上传结果"""
    # 用 pandas 解析 Excel
    try:
        df = pd.read_excel(io.BytesIO(contents), engine="openpyxl")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Excel 文件解析失败: {e}")

    # 获取列名
    columns = df.columns.tolist()

    # 预览前 5 行
    preview_df = df.head(5)
    preview = preview_df.fillna("").to_dict(orient="records")

    # 自动检测映射
    mapping = auto_detect_mapping(columns)

    # 总行数
    total_rows = len(df)

    # 保存到临时 JSON 文件
    upload_id = str(uuid.uuid4())
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    json_path = UPLOAD_DIR / f"{upload_id}.json"
    data = df.fillna("").to_dict(orient="records")
    json_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    return {
        "upload_id": upload_id,
        "columns": columns,
        "preview": preview,
        "mapping": mapping,
        "total_rows": total_rows,
    }


@router.post("")
async def upload_file(file: UploadFile = File(...)):
    """上传 Excel 文件并解析（multipart/form-data 方式）"""
    filename = file.filename or ""
    if not (filename.endswith(".xlsx") or filename.endswith(".xls")):
        raise HTTPException(status_code=400, detail="仅支持 .xlsx 和 .xls 格式的文件")

    contents = await file.read()
    return _parse_excel_and_save(contents, filename)


class Base64UploadRequest(BaseModel):
    """Base64 编码上传请求"""
    filename: str = Field(..., description="文件名")
    data: str = Field(..., description="Base64 编码的文件内容")


@router.post("/base64")
async def upload_base64(req: Base64UploadRequest):
    """上传 Excel 文件并解析（Base64 JSON 方式，兼容代理环境）"""
    filename = req.filename
    if not (filename.endswith(".xlsx") or filename.endswith(".xls")):
        raise HTTPException(status_code=400, detail="仅支持 .xlsx 和 .xls 格式的文件")

    try:
        contents = base64.b64decode(req.data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Base64 解码失败: {e}")

    return _parse_excel_and_save(contents, filename)
