import os
from moviepy.editor import VideoFileClip

def resize_and_crop(clip, target_size):
    """
    Resize and crop the video clip to strictly match target_size.
    Logic helps maintain aspect ratio.
    """
    w, h = clip.size
    target_w, target_h = target_size
    
    # If dimensions match exactly, return original
    if w == target_w and h == target_h:
        return clip
    
    aspect_ratio = w / h
    target_aspect = target_w / target_h
    
    if aspect_ratio > target_aspect:
        # Video is wider than target, resize by height
        new_h = target_h
        new_w = int(w * (target_h / h))
        clip = clip.resize(height=new_h)
    else:
        # Video is taller/narrower, resize by width
        new_w = target_w
        new_h = int(h * (target_w / w))
        clip = clip.resize(width=new_w)
        
    # Center crop
    clip = clip.crop(width=target_w, height=target_h, x_center=clip.w/2, y_center=clip.h/2)
    return clip

def preprocess_videos(assets_dir, target_res, progress_callback=None):
    """
    Recursively find all mp4 files in assets_dir/video and resize/crop them to target_res.
    Overwrites the original files.
    """
    video_root = os.path.join(assets_dir, "video")
    if not os.path.exists(video_root):
        return 0, f"Error: {video_root} does not exist."

    # Collect all video files
    all_files = []
    for root, dirs, files in os.walk(video_root):
        for f in files:
            if f.lower().endswith('.mp4'):
                all_files.append(os.path.join(root, f))
                
    total = len(all_files)
    if total == 0:
        return 0, "No video files found."
        
    processed_count = 0
    
    for idx, v_path in enumerate(all_files):
        # Progress
        if progress_callback:
            progress_callback(idx / total, f"Processing {idx+1}/{total}: {os.path.basename(v_path)}")
            
        temp_path = v_path + ".temp.mp4"
        clip = None
        new_clip = None
        
        try:
            clip = VideoFileClip(v_path)
            w, h = clip.size
            tw, th = target_res
            
            # Skip if already correct
            if w == tw and h == th:
                clip.close()
                continue
                
            new_clip = resize_and_crop(clip, target_res)
            
            # Write to temp file
            # Use a moderate preset to ensure it's not too slow, but quality is decent.
            fps = clip.fps if clip.fps else 30
            
            new_clip.write_videofile(
                temp_path,
                fps=fps,
                codec='libx264',
                audio_codec='aac',
                preset='ultrafast', # Use ultrafast for preprocessing speed, or fast
                logger=None,
                threads=4
            )
            
            # Close clips to release file handles
            new_clip.close()
            clip.close()
            # del crop # Removed erroneous line
            del new_clip
            del clip
            
            # Replace file
            os.remove(v_path)
            os.rename(temp_path, v_path)
            processed_count += 1
            
        except Exception as e:
            print(f"Failed to process {v_path}: {e}")
            # cleanup
            if clip: 
                try: clip.close() 
                except: pass
            if new_clip: 
                try: new_clip.close() 
                except: pass
            if os.path.exists(temp_path):
                os.remove(temp_path)
    
    if progress_callback:
        progress_callback(1.0, "Processing Completed!")
        
    return processed_count, f"Processed {processed_count} files."
