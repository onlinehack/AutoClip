from pydantic import BaseModel
from typing import List, Optional

class FolderWeight(BaseModel):
    folder: str
    weight: int
    speed: float = 1.0
    clip_min_duration: float = 0.0
    clip_max_duration: float = 0.0

class MixConfig(BaseModel):
    audio_path: str
    srt_path: Optional[str] = None
    folder_weights: List[FolderWeight]
    batch_count: int = 1
    width: int = 1080
    height: int = 1920
    bgm_file: Optional[str] = None
    output_tag: str = ""
    
    # Transition Configuration
    # Options: "None", "Crossfade", "Fade to Black"
    transition_type: str = "None" 
    transition_duration: float = 0.5
    
    # Subtitle Configuration
    subtitle_font_name: str = "Noto Sans CJK SC"
    subtitle_font_size: int = 9
    subtitle_color: str = "#FFFFFF"
    subtitle_outline: int = 1
    subtitle_shadow: int = 1
    subtitle_margin_v: int = 15
    subtitle_bold: bool = True
