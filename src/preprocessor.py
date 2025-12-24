import os
import subprocess
import json
import concurrent.futures
import multiprocessing
import shutil

def get_video_info(file_path):
    """
    Get video width and height using ffprobe.
    Returns: (width, height)
    """
    try:
        cmd = [
            "ffprobe", 
            "-v", "error", 
            "-select_streams", "v:0", 
            "-show_entries", "stream=width,height", 
            "-of", "json", 
            file_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        stream = data["streams"][0]
        return int(stream["width"]), int(stream["height"])
    except Exception as e:
        print(f"Error reading info for {file_path}: {e}")
        return None

def process_single_video_task(args):
    """
    Worker task for processing a single video using FFmpeg directly.
    args: (v_path, target_res)
    Returns: (success_bool, v_path_or_error_msg)
    """
    v_path, target_res = args
    temp_path = v_path + ".temp.mp4"
    
    try:
        # 1. Check current dimensions
        info = get_video_info(v_path)
        if not info:
            return False, f"{v_path}: Could not read metadata"
            
        w, h = info
        tw, th = target_res
        
        # Skip if already correct dimensions
        if w == tw and h == th:
            return True, None # Skipped/Success
        
        # 2. Construct FFmpeg command
        # Logic: 
        # - If Landscape (w > h): Fit inside (decrease), then Pad with black.
        # - If Portrait/Square (w <= h): Fill (increase), then Crop center.
        
        if w > h:
            # Landscape -> Letterbox (Pad)
            # scale to fit inside target box, then pad with black to match target resolution
            # pad=w:h:x:y:color
            vf_filter = (
                f"scale=w={tw}:h={th}:force_original_aspect_ratio=decrease,"
                f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2:black"
            )
        else:
            # Portrait/Square -> Zoom to Fill (Crop)
            # efficient logic: scale=w=TARGET_W:h=TARGET_H:force_original_aspect_ratio=increase,crop=TARGET_W:TARGET_H
            vf_filter = (
                f"scale=w={tw}:h={th}:force_original_aspect_ratio=increase,"
                f"crop={tw}:{th}:x=(in_w-{tw})/2:y=(in_h-{th})/2"
            )
        
        cmd = [
            "ffmpeg",
            "-y",                # Overwrite output
            "-i", v_path,
            "-vf", vf_filter,
            "-c:v", "libx264",
            "-preset", "ultrafast",   # Speed priority
            "-crf", "23",
            "-c:a", "aac",            # Encode audio
            "-b:a", "128k",
            "-threads", "2",          # Limit threads per process to allow higher parallelism
            "-loglevel", "error",     # Quiet output
            temp_path
        ]
        
        # Run FFmpeg
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        
        # 3. Replace file
        if os.path.exists(v_path):
            os.remove(v_path)
        os.rename(temp_path, v_path)
        
        return True, v_path
        
    except subprocess.CalledProcessError as e:
        stderr_output = e.stderr.decode() if e.stderr else "Unknown error"
        if os.path.exists(temp_path):
            try: os.remove(temp_path)
            except: pass
        return False, f"{v_path}: FFmpeg failed - {stderr_output}"
    except Exception as e:
        if os.path.exists(temp_path):
            try: os.remove(temp_path)
            except: pass
        return False, f"{v_path}: {str(e)}"

def preprocess_videos(assets_dir, target_res, progress_callback=None):
    """
    Recursively find all mp4 files in assets_dir/video and resize/crop them to target_res.
    Uses parallel FFmpeg processes to utilize multi-core CPUs (Xeon friendly).
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
    
    # Determine number of workers for Xeon / Multi-core
    # We use independent FFmpeg processes.
    # Each FFmpeg is set to use 2 threads.
    # We can aim for roughly (Total Threads) concurrent FFmpegs, or slightly less for IO safety.
    # For a Xeon with say 48 threads, we can run 20-24 workers.
    
    cpu_count = multiprocessing.cpu_count()
    
    # Strategy: Assign roughly 1 worker per 2 logical cores, assuming FFmpeg takes ~200% CPU.
    # Reserve slight overhead.
    max_workers = max(1, int(cpu_count / 2)) 
    
    # Cap workers if file count is small
    max_workers = min(max_workers, total)
    
    # Hard limit to avoid OS file handle exhaustion or extreme IO saturation (e.g. 32 concurrent writes might be HDD bottleneck)
    # 16 is a safe sweet spot for fast SSDs. For RAID/Nvme on Server maybe 32.
    # Let's cap at 16 to be safe unless user asks for more. 
    # Actually wait, user has Xeon server. They might have NVMe. 
    # Let's trust the CPU count but cap at 20 to be safe on IO.
    if max_workers > 24:
        max_workers = 24
        
    print(f"Starting preprocessing with {max_workers} concurrent FFmpeg workers...")

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
                msg = f"Processing {(i + 1)}/{total} | Workers: {max_workers}"
                progress_callback(progress, msg)
    
    if progress_callback:
        progress_callback(1.0, "Processing Completed!")
        
    return processed_count, f"Processed {processed_count} files."
