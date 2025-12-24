import os
import json
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


class AutoClipPipeline:
    def __init__(self, assets_dir: str, output_dir: str):
        self.assets_dir = assets_dir
        self.output_dir = output_dir
        self.matcher = Matcher(assets_dir)

    def run(self, config: MixConfig, progress_callback=None):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        batch_dir = os.path.join(self.output_dir, f"{timestamp}_Batch")
        os.makedirs(batch_dir, exist_ok=True)
        print(f"[{datetime.now()}] [Pipeline] Output Directory: {batch_dir}")
        print(f"[{datetime.now()}] [Pipeline] Config: BatchCount={config.batch_count}, Resolution={config.width}x{config.height}")
        
        # Determine SRT path
        srt_path = config.srt_path
        if not srt_path:
            # Generate SRT
            if progress_callback:
                progress_callback(0.05, "Auto-generating Subtitles (FunASR)...")
            
            print(f"[{datetime.now()}] [Pipeline] ASR start for {config.audio_path}...")
            srt_name = f"generated_{timestamp}.srt"
            srt_path = os.path.join(batch_dir, srt_name)
            srt_path = os.path.join(batch_dir, srt_name)
            generate_srt(config.audio_path, srt_path)
            print(f"[{datetime.now()}] [Pipeline] ASR completed. Output: {srt_path}")
            
        # Load Audio
        time.sleep(1) # Give system a moment
        if progress_callback:
            progress_callback(0.1, "Loading Assets...")
            
        print(f"[{datetime.now()}] [Pipeline] Validating Audio Duration: {config.audio_path}")
        try:
            with AudioFileClip(config.audio_path) as temp_audio:
                total_duration = temp_audio.duration
            print(f"[{datetime.now()}] Audio duration: {total_duration}s")
        except Exception as e:
            print(f"[{datetime.now()}] Error loading audio: {e}")
            raise e
        
        # Load SRT
        print(f"[{datetime.now()}] [Pipeline] Loading SRT: {srt_path}")
        subs = pysrt.open(srt_path)
        print(f"[{datetime.now()}] [Pipeline] SRT loaded. {len(subs)} lines.")
        
        # Old segments logic removed.


        generated_files = []

        for i in range(config.batch_count):
            print(f"[{datetime.now()}] [Pipeline] === Starting Batch {i+1}/{config.batch_count} ===")
            
            # Reload audio for each batch to ensure fresh file handles
            main_audio = AudioFileClip(config.audio_path)
            
            batch_metadata = []
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
            
            print(f"[{datetime.now()}] [Pipeline] Timeline planned with {len(timeline_blocks)} blocks.")

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

                print(f"[{datetime.now()}] [Pipeline] [Batch {i+1}] Rendering Chunk {idx+1}/{len(render_tasks)}: {task['start']:.2f}s - {task['end']:.2f}s (Dur: {task['duration']:.2f}s)")
                
                chunk_start = task["start"]
                chunk_end = task["end"]
                duration = task["duration"]
                folder = task["folder"]
                
                try:
                    # Get Video Clip
                    video_clip = None
                    if folder:
                        print(f"[{datetime.now()}] [Pipeline] Searching clip in: {os.path.basename(folder)}")
                        video_clip, segment_meta = self.matcher.get_ordered_clip(folder, duration)
                        
                        if video_clip:
                            # Apply to metadata
                            batch_metadata.append({
                                "chunk_index": idx,
                                "timeline_start": chunk_start,
                                "timeline_end": chunk_end,
                                "segments": segment_meta
                            })
                    
                    if not video_clip:
                         # Fallback to color clip
                         print(f"[{datetime.now()}] Warning: No video found for chunk {idx}, using black placeholder.")
                         video_clip = ColorClip(size=(config.width, config.height), color=(0,0,0), duration=duration)
                    else:
                        video_clip = self.matcher.resize_and_crop(video_clip, (config.width, config.height))
                    
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
                        threads=8,
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
                
            print(f"[{datetime.now()}] [Pipeline] All chunks rendered. Concatenating {len(part_files)} parts...")
            
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
                if progress_callback:
                    progress_callback(0.85, f"Batch {i+1}: Assembling & syncing audio...")
                
                final_duration = main_audio.duration
                if final_video_visual.duration > final_duration:
                     print(f"[{datetime.now()}] Video ({final_video_visual.duration}s) > Audio ({final_duration}s). Clipping video.")
                     final_video_visual = final_video_visual.subclip(0, final_duration)
                elif final_video_visual.duration < final_duration:
                     print(f"[{datetime.now()}] Video ({final_video_visual.duration}s) < Audio ({final_duration}s). Padding video (or letting it hold).")
                     final_video_visual = final_video_visual.set_duration(final_duration)
                     
                # Overlay Subtitles Globally
                # Subtitles will be burnt in via FFmpeg filter during write_videofile
                if progress_callback:
                    progress_callback(0.9, f"Batch {i+1}: Preparing subtitle filter...")
                print(f"[{datetime.now()}] Subtitles will be added via ffmpeg filter.")

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
                print(f"[{datetime.now()}] [Pipeline] Saving Final Video to {output_filename}")
                print(f"[{datetime.now()}] [Pipeline] This step includes FFmpeg encoding and burning subtitles. Please wait...")

                if progress_callback:
                    progress_callback(0.95, f"Batch {i+1}: Encoding final video (this may take a while)...")
                
                # Prepare subtitle filter args
                # Use forward slashes and ensure absolute path for filter
                srt_abspath = os.path.abspath(srt_path)
                
                print(f"\n[{datetime.now()}] --- Subtitle Debug Info ---")
                print(f"Environment: {os.name} (posix=Linux/Mac, nt=Windows)")
                print(f"Original SRT Path: {srt_path}")
                print(f"Absolute SRT Path: {srt_abspath}")
                
                if os.path.exists(srt_abspath):
                    print(f"SRT File Exists. Size: {os.path.getsize(srt_abspath)} bytes")
                else:
                    print(f"CRITICAL: SRT file does NOT exist at {srt_abspath}")

                # Default to original
                final_srt_path = srt_abspath

                # Apply offset to align subtitles (User requested "slower"/later)
                # Shifting by -0.5 seconds to appear EARLIER (counteract lag)
                SHIFT_SECONDS = -0.5
                try:
                    print(f"[{datetime.now()}] Applying {SHIFT_SECONDS}s shift to subtitles (Advanced/Earlier)...")
                    
                    # Open the ORIGINAL (or current) SRT to shift it
                    subs_obj = pysrt.open(srt_abspath)
                    subs_obj.shift(seconds=SHIFT_SECONDS)
                    
                    shifted_srt_name = f"shifted_{os.path.basename(srt_path)}"
                    shifted_srt_path = os.path.join(batch_dir, shifted_srt_name)
                    subs_obj.save(shifted_srt_path, encoding='utf-8')
                    
                    final_srt_path = os.path.abspath(shifted_srt_path)
                    print(f"[{datetime.now()}] Subtitles shifted. Using NEW SRT file: {final_srt_path}")
                except Exception as e:
                    print(f"[{datetime.now()}] Error shifting subtitles: {e}")
                    print(f"[{datetime.now()}] Fallback to ORIGINAL SRT: {final_srt_path}")

                # Path formatting for FFmpeg 'subtitles' filter
                # 1. Normalize slashes to forward slashes (works on both Linux and Windows for FFmpeg)
                srt_filter_path = final_srt_path.replace('\\', '/')
                
                # 2. Handle Windows drive letters specifically
                if os.name == 'nt':
                    # On Windows, 'C:/' -> 'C\:/' for filter escaping
                    srt_filter_path = srt_filter_path.replace(':', '\\:')
                
                print(f"Escaped Path for Filter: {srt_filter_path}")
                
                # Convert color from valid Hex #RRGGBB to ASS &H00BBGGRR
                def hex_to_ass(hex_color):
                    c = hex_color.lstrip('#')
                    if len(c) == 6:
                        r, g, b = c[0:2], c[2:4], c[4:6]
                        # ASS format: &HAABBGGRR (AA=Alpha)
                        return f"&H00{b}{g}{r}".upper()
                    return "&H00FFFFFF"

                primary_color_ass = hex_to_ass(config.subtitle_color)
                
                # NOTE: Fontname with spaces can be tricky. We escape spaces with backslash just in case.
                font_name = config.subtitle_font_name
                font_name_escaped = font_name.replace(" ", r"\ ")
                
                style_str = (
                    f"Fontname={font_name_escaped},FontSize={config.subtitle_font_size},"
                    f"PrimaryColour={primary_color_ass},Outline={config.subtitle_outline},"
                    f"Shadow={config.subtitle_shadow},MarginV={config.subtitle_margin_v},"
                    f"Alignment=2,Bold={1 if config.subtitle_bold else 0}"
                )

                ffmpeg_params = [
                    '-vf', 
                    f"subtitles='{srt_filter_path}':force_style='{style_str}'"
                ]
                print(f"Final ffmpeg_params output: {ffmpeg_params}")
                print(f"---------------------------------\n")
                
                # Write file
                final_video.write_videofile(
                    output_filename, 
                    fps=24, 
                    codec='libx264', 
                    audio_codec='aac',
                    threads=16,
                    logger=None,
                    ffmpeg_params=ffmpeg_params
                )
                print(f"[{datetime.now()}] [Pipeline] Video encoding finished: {output_filename}")
                generated_files.append(output_filename)
                
                # Save Metadata
                meta_filename = output_filename.replace('.mp4', '_metadata.json')
                try:
                    with open(meta_filename, 'w', encoding='utf-8') as f:
                        json.dump(batch_metadata, f, indent=2, ensure_ascii=False)
                    print(f"[{datetime.now()}] Metadata saved to {meta_filename}")
                except Exception as e:
                    print(f"Error saving metadata: {e}")
                
            finally:
                # Close all clips
                for c in clip_objects:
                    c.close()
                if 'final_video' in locals(): final_video.close()
                if 'main_audio' in locals(): main_audio.close()

        # Cleanup shared resources


        return generated_files
