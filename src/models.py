from pydantic import BaseModel
from typing import List, Optional

class FolderWeight(BaseModel):
    folder: str
    weight: int

class MixConfig(BaseModel):
    audio_path: str
    srt_path: Optional[str] = None
    folder_weights: List[FolderWeight]
    batch_count: int = 1
    width: int = 1080
    height: int = 1920
    bgm_file: Optional[str] = None
