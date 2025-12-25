import os
import subprocess
import argparse
from pathlib import Path
import time
from datetime import datetime
import concurrent.futures
import multiprocessing

def check_ffmpeg():
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def get_video_files(directory):
    video_extensions = {'.mp4', '.mov', '.avi', '.mkv', '.flv', '.wmv'}
    video_files = []
    for root, _, files in os.walk(directory):
        for file in files:
            if Path(file).suffix.lower() in video_extensions:
                video_files.append(os.path.join(root, file))
    return video_files

import shutil

def get_video_size(input_path):
    """Returns (width, height) or None if failed."""
    try:
        cmd = [
            "ffprobe", 
            "-v", "error", 
            "-select_streams", "v:0", 
            "-show_entries", "stream=width,height", 
            "-of", "csv=s=x:p=0", 
            input_path
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, text=True)
        w_str, h_str = result.stdout.strip().split('x')
        return int(w_str), int(h_str)
    except Exception:
        return None

def process_video(input_path, output_path, target_width=1080, target_height=1920):
    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    # Check current resolution
    current_size = get_video_size(input_path)
    if current_size:
        cw, ch = current_size
        if cw == target_width and ch == target_height:
            print(f"[Info] {os.path.basename(input_path)} already matches target {target_width}x{target_height}. Skipping re-encode.")
            
            # If input and output are different files, copy instead of re-encoding
            if os.path.normpath(os.path.abspath(input_path)) != os.path.normpath(os.path.abspath(output_path)):
                try:
                    shutil.copy2(input_path, output_path)
                    print(f"       -> Copied to destination.")
                except Exception as e:
                    print(f"[Error] Failed to copy file: {e}")
                    return False
            return True

    # FFmpeg command
    # -vf scale=w:h:force_original_aspect_ratio=decrease,pad=w:h:(ow-iw)/2:(oh-ih)/2
    #     -> Scales to fit INSIDE the target box (decrease)
    #     -> Pads with black bars to reach target size (center)
    
    cmd = [
        "ffmpeg",
        "-y",
        "-i", input_path,
        "-vf", f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2",
        "-c:v", "libx264",
        "-preset", "faster", 
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        output_path
    ]
    
    start_time = time.time()
    try:
        # Run ffmpeg
        subprocess.run(cmd, check=True, stderr=subprocess.PIPE)
        duration = time.time() - start_time
        print(f"[Done] {os.path.basename(input_path)} -> {duration:.1f}s")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[Error] Failed to process {input_path}")
        # print(e.stderr.decode()) # Optional: print error details
        return False

def process_video_task(args):
    """
    Helper function for parallel processing to unpack arguments.
    args: (input_path, output_path, target_width, target_height)
    """
    input_path, output_path, target_width, target_height = args
    return input_path, process_video(input_path, output_path, target_width, target_height)

def batch_process_parallel(files_tasks, max_workers=None, progress_callback=None):
    """
    Execute video processing in parallel.
    files_tasks: List of tuples (input_path, output_path, target_width, target_height)
    """
    if max_workers is None:
        # Default to fewer workers if not specified to avoid choking I/O
        # A conservative default: CPU count / 2, capped at 8 to prevent disk IO saturation
        try:
            cpu_count = os.cpu_count() or 4
            max_workers = max(1, min(cpu_count, 8)) 
        except:
            max_workers = 4
            
    results = []
    total = len(files_tasks)
    
    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_file = {executor.submit(process_video_task, task): task[0] for task in files_tasks}
        
        for i, future in enumerate(concurrent.futures.as_completed(future_to_file)):
            input_file = future_to_file[future]
            try:
                _, success = future.result()
                results.append(success)
            except Exception as e:
                print(f"[Error] Task failed for {input_file}: {e}")
                results.append(False)
            
            if progress_callback:
                progress_callback(i + 1, total)
                
    return results

def main():
    parser = argparse.ArgumentParser(description="Pre-process video assets to standard 1080p.")
    parser.add_argument("--input", default="assets/video", help="Input directory containing raw videos")
    parser.add_argument("--output", default="assets/video_optimized", help="Output directory for optimized videos")
    
    parser.add_argument("--workers", type=int, default=None, help="Number of parallel workers (default: auto)")
    
    args = parser.parse_args()
    
    if not check_ffmpeg():
        print("Error: FFmpeg is not installed or not in PATH.")
        return

    input_dir = os.path.abspath(args.input)
    output_dir = os.path.abspath(args.output)
    
    if not os.path.exists(input_dir):
        print(f"Error: Input directory '{input_dir}' does not exist.")
        return

    print(f"[{datetime.now()}] Starting Batch Processing...")
    print(f"Input:  {input_dir}")
    print(f"Output: {output_dir}")
    
    files = get_video_files(input_dir)
    total_files = len(files)
    print(f"Found {total_files} video files.")
    
    success_count = 0
    start_total_time = time.time()
    times = []
    
    
    # Prepare tasks
    tasks = []
    for fpath in files:
        rel_path = os.path.relpath(fpath, input_dir)
        out_path = os.path.join(output_dir, rel_path)
        out_path = str(Path(out_path).with_suffix('.mp4'))
        
        # Consistent fixed target for CLI (customize as needed)
        # The original code hardcoded 1080x1920 inside process_video default args, 
        # but here we should be explicit or allow args.
        # For now, we preserve 1080x1920 vertical default unless changed.
        tasks.append((fpath, out_path, 1080, 1920))

    if args.workers:
        print(f"Using {args.workers} parallel workers.")
    else:
        print("Using automatic parallel worker count.")

    def cli_progress(current, total):
        print(f"\rProgress: [{current}/{total}]", end="", flush=True)

    # Run parallel
    results = batch_process_parallel(tasks, max_workers=args.workers, progress_callback=cli_progress)
    success_count = sum(results)
    
    print() # Newline after progress

    total_duration = time.time() - start_total_time
    print(f"\n[{datetime.now()}] Finished. {success_count}/{total_files} processed.")
    print(f"Total Time: {total_duration:.2f}s | Avg per file: {(total_duration/total_files) if total_files else 0:.2f}s")

if __name__ == "__main__":
    main()
