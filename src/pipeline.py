import os
import time
import pysrt
from datetime import datetime
from typing import List
from moviepy.editor import concatenate_videoclips, AudioFileClip, CompositeVideoClip, CompositeAudioClip, VideoFileClip
# ColorClip might be needed for blank segments if no video found
from moviepy.video.VideoClip import ColorClip

from src.models import MixConfig
# from src.utils import split_text # No longer needed
from src.processors.asr import generate_srt
from src.processors.matcher import Matcher
from src.processors.subtitle import create_subtitle_clip

class AutoClipPipeline:
    def __init__(self, assets_dir: str, output_dir: str):
        self.assets_dir = assets_dir
        self.output_dir = output_dir
        self.matcher = Matcher(assets_dir)

    def run(self, config: MixConfig, progress_callback=None):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        batch_dir = os.path.join(self.output_dir, f"{timestamp}_Batch")
        os.makedirs(batch_dir, exist_ok=True)
        
        # Determine SRT path
        srt_path = config.srt_path
        if not srt_path:
            # Generate SRT
            if progress_callback:
                progress_callback(0.05, "Auto-generating Subtitles (FunASR)...")
            
            print(f"[{datetime.now()}] Starting ASR generation...")
            srt_name = f"generated_{timestamp}.srt"
            srt_path = os.path.join(batch_dir, srt_name)
            generate_srt(config.audio_path, srt_path)
            print(f"[{datetime.now()}] ASR generation completed. Memory cleanup should be done.")
            
        # Load Audio
        time.sleep(1) # Give system a moment
        if progress_callback:
            progress_callback(0.1, "Loading Assets...")
            
        print(f"[{datetime.now()}] Loading AudioFileClip: {config.audio_path}")
        try:
            main_audio = AudioFileClip(config.audio_path)
            total_duration = main_audio.duration
            print(f"[{datetime.now()}] Audio loaded. Duration: {total_duration}s")
        except Exception as e:
            print(f"[{datetime.now()}] Error loading audio: {e}")
            raise e
        
        # Load SRT
        print(f"[{datetime.now()}] Loading SRT: {srt_path}")
        subs = pysrt.open(srt_path)
        print(f"[{datetime.now()}] SRT loaded. {len(subs)} subtitles.")
        
        # Old segments logic removed.


        generated_files = []

        for i in range(config.batch_count):
            if progress_callback:
                progress_callback(0.2, f"Batch {i+1}: Planning Timeline...")

            # 1. Plan Strategy (Timeline)
            # Allocation of time per folder based on weights
            total_weight = sum(fw.weight for fw in config.folder_weights)
            
            timeline_blocks = []
            current_t = 0.0
            
            for fw in config.folder_weights:
                if total_weight > 0:
                    share = fw.weight / total_weight
                    duration_share = share * total_duration
                else:
                    duration_share = 0
                
                timeline_blocks.append({
                    "folder": os.path.join(self.assets_dir, "video", fw.folder),
                    "start": current_t,
                    "end": current_t + duration_share
                })
                current_t += duration_share
            
            # Ensure last block covers floating point errors
            if timeline_blocks:
                timeline_blocks[-1]["end"] = max(total_duration, timeline_blocks[-1]["end"])

            # 2. Assemble Video Tracks - RENDER CHUNKS IMMEDIATELY TO AVOID OOM
            temp_parts_dir = os.path.join(batch_dir, "parts")
            os.makedirs(temp_parts_dir, exist_ok=True)
            
            part_files = []
            
            # Create render tasks from timeline_blocks
            # Subdivide blocks to avoid huge memory usage
            MAX_CHUNK_DURATION = 15.0 
            render_tasks = []
            
            for block in timeline_blocks:
                b_start = block["start"]
                b_end = block["end"]
                folder = block["folder"]
                
                curr = b_start
                while curr < b_end:
                    next_t = min(curr + MAX_CHUNK_DURATION, b_end)
                    render_tasks.append({
                        "start": curr,
                        "end": next_t,
                        "folder": folder,
                        "duration": next_t - curr
                    })
                    curr = next_t

            batch_start_time = time.time()
            last_step_time = time.time()
            
            for idx, task in enumerate(render_tasks):
                current_time = time.time()
                elapsed = current_time - batch_start_time
                step_dur = current_time - last_step_time if idx > 0 else 0
                last_step_time = current_time
                
                msg = f"Batch {i+1}: Rendering part {idx+1}/{len(render_tasks)} | Elapsed: {elapsed:.1f}s"
                if idx > 0:
                    msg += f" (Last: {step_dur:.1f}s)"
                    
                if progress_callback:
                    progress_callback(0.2 + 0.6 * (idx / len(render_tasks)), msg)

                print(f"[{datetime.now()}] Processing chunk {idx+1}/{len(render_tasks)} [{task['start']:.2f}-{task['end']:.2f}] | {msg}")
                
                chunk_start = task["start"]
                chunk_end = task["end"]
                duration = task["duration"]
                folder = task["folder"]
                
                try:
                    # Get Video Clip
                    video_clip = None
                    if folder:
                        print(f"[{datetime.now()}] Getting clip from folder: {os.path.basename(folder)}")
                        video_clip = self.matcher.get_ordered_clip(folder, duration)

                    if not video_clip:
                         # Fallback to color clip
                         print(f"[{datetime.now()}] Warning: No video found for chunk {idx}, using black placeholder.")
                         video_clip = ColorClip(size=(config.width, config.height), color=(0,0,0), duration=duration)
                    # else:
                    #     video_clip = self.matcher.resize_and_crop(video_clip, (config.width, config.height))
                    
                    video_clip = video_clip.set_duration(duration)
                    
                    # RENDER PART IMMEDIATELY (VIDEO ONLY)
                    part_file = os.path.join(temp_parts_dir, f"part_{idx:04d}.mp4")
                    print(f"[{datetime.now()}] Rendering video part to {part_file}...")
                    
                    video_clip.write_videofile(
                        part_file, 
                        fps=24, 
                        codec='libx264',
                        audio=False, 
                        preset='ultrafast',
                        logger=None
                    )
                    
                    part_files.append(part_file)
                    
                    # CLEANUP
                    video_clip.close()
                    del video_clip
                    
                    import gc
                    gc.collect()
                    
                except Exception as e:
                    print(f"[{datetime.now()}] Error processing chunk {idx}: {e}")
                    raise e

            # Concatenate Parts
            if not part_files:
                continue
                
            print(f"[{datetime.now()}] Concatenating {len(part_files)} parts...")
            
            # Load all parts
            # Logic: If we load 50 VideoFileClips, do we crash?
            # It's safer to use ffmpeg concat demuxer if possible, but let's try MoviePy concat first.
            # If it fails, we fall back to file-list concat.
            
            clip_objects = []
            try:
                for pf in part_files:
                    clip_objects.append(VideoFileClip(pf))
                    
                final_video_visual = concatenate_videoclips(clip_objects, method="compose")
                
                # Set Audio
                final_duration = main_audio.duration
                if final_video_visual.duration > final_duration:
                     print(f"[{datetime.now()}] Video ({final_video_visual.duration}s) > Audio ({final_duration}s). Clipping video.")
                     final_video_visual = final_video_visual.subclip(0, final_duration)
                elif final_video_visual.duration < final_duration:
                     print(f"[{datetime.now()}] Video ({final_video_visual.duration}s) < Audio ({final_duration}s). Padding video (or letting it hold).")
                     final_video_visual = final_video_visual.set_duration(final_duration)
                     
                # Overlay Subtitles Globally
                print(f"[{datetime.now()}] Generating global subtitle overlay...")
                subtitle_clips = []
                for sub in subs:
                    s_start = sub.start.ordinal / 1000.0
                    s_end = sub.end.ordinal / 1000.0
                    s_dur = s_end - s_start
                    
                    if s_dur > 0 and sub.text.strip():
                        # We use the full duration for the clip, but set start time
                        txt = create_subtitle_clip(
                            sub.text, 
                            duration=s_dur, 
                            size=(config.width, config.height)
                        ).set_start(s_start)
                        subtitle_clips.append(txt)
                
                if subtitle_clips:
                    # Use CompositeVideoClip to overlay text on video
                    # Note: We must ensure the video is the first element (layer 0)
                    final_video_visual = CompositeVideoClip([final_video_visual] + subtitle_clips)

                final_video = final_video_visual.set_audio(main_audio)
                
                # Add BGM
                if config.bgm_file:
                    bgm_path = os.path.join(self.assets_dir, "bgm", config.bgm_file)
                    if os.path.exists(bgm_path):
                        from moviepy.audio.fx.all import audio_loop, volumex
                        bgm_clip = AudioFileClip(bgm_path)
                        # Loop bgm
                        bgm_clip = audio_loop(bgm_clip, duration=final_video.duration)
                        bgm_clip = bgm_clip.fx(volumex, 0.3)
                        # Composite
                        final_audio = CompositeAudioClip([final_video.audio, bgm_clip])
                        final_video = final_video.set_audio(final_audio)

                output_filename = os.path.join(batch_dir, f"batch_{i+1}.mp4")
                print(f"[{datetime.now()}] Writing final video to {output_filename}")
                
                # Write file
                final_video.write_videofile(
                    output_filename, 
                    fps=24, 
                    codec='libx264', 
                    audio_codec='aac',
                    threads=4,
                    logger=None 
                )
                generated_files.append(output_filename)
                
            finally:
                # Close all clips
                for c in clip_objects:
                    c.close()
                if 'final_video' in locals(): final_video.close()
                if 'main_audio' in locals(): main_audio.close()

        return generated_files
