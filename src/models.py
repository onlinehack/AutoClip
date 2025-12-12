from pydantic import BaseModel
from typing import List, Optional

class FolderWeight(BaseModel):
    folder: str
    weight: int

class MixConfig(BaseModel):
    text: str
    voice: str = "zh-CN-XiaoxiaoNeural"
    folder_weights: List[FolderWeight]
    batch_count: int = 1
    width: int = 1080
    height: int = 1920
    bgm_file: Optional[str] = None
