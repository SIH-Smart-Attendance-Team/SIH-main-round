from pydantic import BaseModel
from typing import List, Optional


class DataLink(BaseModel):
    text: str
    url: str
    is_ftp: bool = False


class DataSource(BaseModel):
    label: str
    links: List[DataLink] = []
    note: Optional[str] = None
