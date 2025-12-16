import os
import subprocess
import argparse
from pathlib import Path
import time
from datetime import datetime

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

def process_video(input_path, output_path, target_width=1080, target_height=1920):
    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    # FFmpeg command
    # -vf scale=w:h:force_original_aspect_ratio=increase,crop=w:h
    #     -> Scales to cover the target box (increase)
    #     -> Crops to exact target size (center crop)
    
    cmd = [
        "ffmpeg",
        "-y",
        "-i", input_path,
        "-vf", f"scale={target_width}:{target_height}:force_original_aspect_ratio=increase,crop={target_width}:{target_height}",
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

def main():
    parser = argparse.ArgumentParser(description="Pre-process video assets to standard 1080p.")
    parser.add_argument("--input", default="assets/video", help="Input directory containing raw videos")
    parser.add_argument("--output", default="assets/video_optimized", help="Output directory for optimized videos")
    
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
    
    for i, file_path in enumerate(files):
        current_idx = i + 1
        rel_path = os.path.relpath(file_path, input_dir)
        out_path = os.path.join(output_dir, rel_path)
        out_path = str(Path(out_path).with_suffix('.mp4'))
        
        # UI Header
        print(f"\n--- [{current_idx}/{total_files}] Processing: {rel_path} ---")

        if os.path.exists(out_path):
             print(f"   -> Skipping (Already exists)")
             success_count += 1
             continue
             
        # Process
        item_start = time.time()
        success = process_video(file_path, out_path)
        item_duration = time.time() - item_start
        
        if success:
            success_count += 1
            times.append(item_duration)
            avg_time = sum(times) / len(times)
            elapsed_total = time.time() - start_total_time
            remaining_files = total_files - current_idx
            eta = remaining_files * avg_time
            
            print(f"   -> Done in {item_duration:.2f}s")
            print(f"   -> [Stats] Avg: {avg_time:.2f}s | Elapsed: {elapsed_total:.1f}s | ETA: {eta:.1f}s")
        else:
             print(f"   -> Failed")

    total_duration = time.time() - start_total_time
    print(f"\n[{datetime.now()}] Finished. {success_count}/{total_files} processed.")
    print(f"Total Time: {total_duration:.2f}s | Avg per file: {(total_duration/total_files) if total_files else 0:.2f}s")

if __name__ == "__main__":
    main()
