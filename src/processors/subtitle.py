from moviepy.editor import TextClip, CompositeVideoClip
from typing import List

def create_subtitle_clip(text: str, duration: float, fontsize: int = 60, font: str = 'Noto-Sans-CJK-SC', color: str = 'white', stroke_color: str = 'black', stroke_width: int = 2, size: tuple = (1080, 1920)) -> TextClip:
    """
    Create a subtitle clip for a specific duration.
    Ensures single line and fits within width.
    """
    video_width = size[0]
    max_width = video_width * 0.9  # Safety margin
    
    # Method 1: Iterative scaling
    # Create clip with default fontsize
    txt_clip = TextClip(
        text, 
        fontsize=fontsize, 
        font=font, 
        color=color, 
        stroke_color=stroke_color, 
        stroke_width=stroke_width,
        # method='caption', # REMOVED: caption forces wrapping
        # size=(size[0] * 0.8, None), # REMOVED: we want natural width
        align='center'
    )
    
    # Check width and scale down if necessary
    if txt_clip.w > max_width:
        # Calculate new font size
        scale_ratio = max_width / txt_clip.w
        new_fontsize = int(fontsize * scale_ratio)
        
        # Close old clip to free resource
        txt_clip.close()
        
        # Re-create with smaller font
        txt_clip = TextClip(
            text, 
            fontsize=new_fontsize, 
            font=font, 
            color=color, 
            stroke_color=stroke_color, 
            stroke_width=stroke_width,
            align='center'
        )
    
    txt_clip = txt_clip.set_position(('center', 0.8), relative=True).set_duration(duration)
    return txt_clip
