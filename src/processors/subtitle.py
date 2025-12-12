from moviepy.editor import TextClip, CompositeVideoClip
from typing import List

def create_subtitle_clip(text: str, duration: float, fontsize: int = 60, font: str = 'Noto-Sans-CJK-SC', color: str = 'white', stroke_color: str = 'black', stroke_width: int = 2, size: tuple = (1080, 1920)) -> TextClip:
    """
    Create a subtitle clip for a specific duration.
    """
    # Note: TextClip requires ImageMagick to be configured correctly.
    # We position the text at the bottom.
    
    txt_clip = TextClip(
        text, 
        fontsize=fontsize, 
        font=font, 
        color=color, 
        stroke_color=stroke_color, 
        stroke_width=stroke_width,
        method='caption', # 'caption' allows wrapping
        size=(size[0] * 0.8, None), # Limit width to 80% of screen
        align='center'
    )
    
    txt_clip = txt_clip.set_position(('center', 0.8), relative=True).set_duration(duration)
    return txt_clip
