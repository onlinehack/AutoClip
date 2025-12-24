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

import concurrent.futures
import multiprocessing

def process_single_video_task(args):
    """
    Worker task for processing a single video.
    args: (v_path, target_res)
    Returns: (success_bool, v_path_or_error_msg)
    """
    v_path, target_res = args
    temp_path = v_path + ".temp.mp4"
    clip = None
    new_clip = None
    
    try:
        clip = VideoFileClip(v_path)
        w, h = clip.size
        # Unpack target res
        tw, th = target_res
        
        # Skip if already correct dimensions
        if w == tw and h == th:
            clip.close()
            return True, None # Skipped/Success
            
        new_clip = resize_and_crop(clip, target_res)
        
        # Write to temp file
        # Lower threads per process since we are running multiple processes
        fps = clip.fps if clip.fps else 30
        
        new_clip.write_videofile(
            temp_path,
            fps=fps,
            codec='libx264',
            audio_codec='aac',
            preset='ultrafast', 
            logger=None,
            threads=2  # Reduced threads per worker to avoid oversubscription
        )
        
        # cleanup
        new_clip.close()
        clip.close()
        
        # Replace file
        if os.path.exists(v_path):
            os.remove(v_path)
        os.rename(temp_path, v_path)
        
        return True, v_path
        
    except Exception as e:
        # cleanup on error
        if clip: 
            try: clip.close() 
            except: pass
        if new_clip: 
            try: new_clip.close() 
            except: pass
        if os.path.exists(temp_path):
            try: os.remove(temp_path)
            except: pass
            
        return False, f"{v_path}: {str(e)}"

def preprocess_videos(assets_dir, target_res, progress_callback=None):
    """
    Recursively find all mp4 files in assets_dir/video and resize/crop them to target_res.
    Uses parallel processing to utilize multi-core CPUs (Xeon friendly).
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
    
    # Determine number of workers
    # Leave some cores for the system, but utilize most.
    # For Xeon, cpu_count can be high (e.g. 24).
    # We don't want to spawn too many ffmpeg instances if memory is tight, 
    # but generally 50-75% of cores is safe for video encoding if RAM permits.
    cpu_count = multiprocessing.cpu_count()
    max_workers = max(1, cpu_count - 2) # Leave 2 cores free
    # Cap workers if file count is small
    max_workers = min(max_workers, total)
    
    print(f"Starting preprocessing with {max_workers} workers parallel processing...")

    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        futures = {executor.submit(process_single_video_task, (f, target_res)): f for f in all_files}
        
        for i, future in enumerate(concurrent.futures.as_completed(futures)):
            result_success, result_data = future.result()
            
            if result_success:
                processed_count += 1
            else:
                print(f"Error processing video: {result_data}")

            # Update progress
            if progress_callback:
                progress = (i + 1) / total
                # Use result_data (path) if success, or just generic message
                msg = f"Processing {(i + 1)}/{total}"
                progress_callback(progress, msg)
    
    if progress_callback:
        progress_callback(1.0, "Processing Completed!")
        
    return processed_count, f"Processed {processed_count} files."
