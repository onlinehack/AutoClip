import re
import os
from typing import List

def split_text(text: str) -> List[str]:
    """
    Split text into sentences based on punctuation (。！？\n).
    Filter out empty lines.
    """
    # Split by common sentence terminators and newlines
    # The regex keeps the delimiters if we wanted, but here we just want the content usually.
    # However, for TTS it's often better to split by chunks. 
    # The requirement says: split by 。！？\n
    
    # This regex splits by the delimiters and keeps them? 
    # Let's just split and clean up.
    parts = re.split(r'[。！？\n]', text)
    return [p.strip() for p in parts if p.strip()]

def get_video_files(folder_path: str) -> List[str]:
    """
    Get all .mp4 files in a directory.
    """
    video_extensions = (
        '.mp4', '.mov', '.avi', '.mkv', '.flv', '.wmv', 
        '.webm', '.m4v', '.mpg', '.mpeg', '.3gp', '.ts', '.mts'
    )
    return [
        os.path.join(folder_path, f) 
        for f in os.listdir(folder_path) 
        if f.lower().endswith(video_extensions)
    ]

def get_subfolders(base_path: str) -> List[str]:
    """
    Get all subfolders in a directory.
    """
    if not os.path.exists(base_path):
        return []
    return [
        f for f in os.listdir(base_path) 
        if os.path.isdir(os.path.join(base_path, f))
    ]
