import os
import json
import time
import pysrt
from datetime import datetime
from typing import List
from moviepy.editor import concatenate_videoclips, AudioFileClip, CompositeVideoClip, CompositeAudioClip, VideoFileClip
from moviepy.video.VideoClip import ColorClip
from moviepy.video.fx.all import speedx

from src.models import MixConfig
# from src.utils import split_text # No longer needed
from src.processors.asr import generate_srt
from src.processors.matcher import Matcher
from src.logger import setup_logger

logger = setup_logger("Pipeline")

class AutoClipPipeline:
    def __init__(self, assets_dir: str, output_dir: str):
        self.assets_dir = assets_dir
        self.output_dir = output_dir
        self.matcher = Matcher(assets_dir)

    def run(self, config: MixConfig, progress_callback=None):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # CPU Optimization for Xeon/High-core CPUs
        # Detected cores or default to 16 if retrieval fails
        cpu_cores = os.cpu_count() or 16
        # Limit threads to reasonable max for FFmpeg (usually diminishing returns > 32, but let's allow up to 32 or full usage)
        # For Xeon, using all cores is generally desired.
        # For Xeon, using all cores is generally desired.
        render_threads = max(4, cpu_cores)
        logger.info(f"Multi-core Optimization: Using {render_threads} threads for encoding.")
        
        # Extract audio identifier
        audio_stem = os.path.splitext(os.path.basename(config.audio_path))[0]
        # Sanitize audio name
        safe_audio_name = "".join(c for c in audio_stem if c.isalnum() or c in ('_', '-')).strip()
        
        folder_name = f"{timestamp}_{safe_audio_name}_Batch"
        if config.output_tag:
            # Join with underscore, make sure no weird characters
            safe_tag = "".join(c for c in config.output_tag if c.isalnum() or c in ('_', '-')).strip()
            if safe_tag:
                folder_name = f"{safe_tag}_{folder_name}"
                
        batch_dir = os.path.join(self.output_dir, folder_name)
        os.makedirs(batch_dir, exist_ok=True)
        logger.info(f"Output Directory: {batch_dir}")
        logger.info(f"Config: BatchCount={config.batch_count}, Resolution={config.width}x{config.height}")
        
        # Determine SRT path
        srt_path = config.srt_path
        if not srt_path:
            # Generate SRT
            if progress_callback:
                progress_callback(0.05, "Auto-generating Subtitles (FunASR)...")
            
            logger.info(f"ASR start for {config.audio_path}...")
            srt_name = f"generated_{timestamp}.srt"
            srt_path = os.path.join(batch_dir, srt_name)
            generate_srt(config.audio_path, srt_path)
            logger.info(f"ASR completed. Output: {srt_path}")
            
        # Load Audio
        time.sleep(1) # Give system a moment
        if progress_callback:
            progress_callback(0.1, "Loading Assets...")
            
        logger.info(f"Validating Audio Duration: {config.audio_path}")
        try:
            with AudioFileClip(config.audio_path) as temp_audio:
                total_duration = temp_audio.duration
            logger.info(f"Audio duration: {total_duration}s")
        except Exception as e:
            logger.error(f"Error loading audio: {e}")
            raise e
        
        # Load SRT
        logger.info(f"Loading SRT: {srt_path}")
        subs = pysrt.open(srt_path)
        logger.info(f"SRT loaded. {len(subs)} lines.")
        
        # Old segments logic removed.


        generated_files = []

        for i in range(config.batch_count):
            # Reset used files for this new video to ensure it starts fresh
            # But within this video, it will try not to reuse clips until exhausted.
            self.matcher.reset_usage()

            logger.info(f"=== Starting Batch {i+1}/{config.batch_count} ===")
            
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
                    "speed": fw.speed, # Pass speed config
                    "clip_min_duration": fw.clip_min_duration,
                    "clip_max_duration": fw.clip_max_duration,
                    "start": current_t,
                    "end": current_t + duration_share
                })
                current_t += duration_share
            
            # Ensure last block covers floating point errors
            if timeline_blocks:
                timeline_blocks[-1]["end"] = max(total_duration, timeline_blocks[-1]["end"])
            
            logger.info(f"Timeline planned with {len(timeline_blocks)} blocks.")

            # 2. Assemble Video Tracks - RENDER CHUNKS IMMEDIATELY TO AVOID OOM
            temp_parts_dir = os.path.join(batch_dir, "parts")
            os.makedirs(temp_parts_dir, exist_ok=True)
            
            part_files = []
            
            # Create render tasks from timeline_blocks
            # Subdivide blocks to avoid huge memory usage
            MAX_CHUNK_DURATION = 15.0 
            render_tasks = []
            
            for idx_b, block in enumerate(timeline_blocks):
                b_start = block["start"]
                b_end = block["end"]
                folder = block["folder"]
                speed = block.get("speed", 1.0)
                
                curr = b_start
                while curr < b_end:
                    next_t = min(curr + MAX_CHUNK_DURATION, b_end)
                    
                    is_block_start = (curr == b_start)
                    is_block_end = (next_t == b_end)
                    
                    # Determine global index logic for transition eligibility
                    # We only transition if it is a block boundary AND not the absolute start/end of video
                    # However, since we process blocks in order, we can flag 'needs_trans_in' / 'needs_trans_out'
                    
                    # For Crossfade, we need overlaps between BLOCKS. 
                    # Block N End overlaps with Block N+1 Start.
                    
                    task_info = {
                        "start": curr,
                        "end": next_t,
                        "folder": folder,
                        "speed": speed,
                        "clip_min_duration": block.get("clip_min_duration", 0.0),
                        "clip_max_duration": block.get("clip_max_duration", 0.0),
                        "duration": next_t - curr,
                        "is_block_start": is_block_start,
                        "is_block_end": is_block_end,
                        "block_index": idx_b,
                        "total_blocks": len(timeline_blocks)
                    }
                    render_tasks.append(task_info)
                    
                    curr = next_t

            # Parallel Rendering Setup
            import concurrent.futures
            
            # Optimization for High-Core CPUs (e.g., Xeon)
            # - Use more workers, but limit threads per worker to avoid context switch overhead.
            # Allow up to 16 workers if cores allow (preserving some for system)
            MAX_WORKERS = max(2, min(16, cpu_cores // 2)) 
            # Each worker gets remaining threads distributed, but capped at 4-6 is usually sweet spot for 1080p
            THREADS_PER_JOB = max(2, min(8, int(cpu_cores / MAX_WORKERS)))
            
            logger.info(f"Parallel Rendering: {MAX_WORKERS} workers, {THREADS_PER_JOB} threads/worker.")
            
            def render_chunk_worker(idx, task, video_clip, output_path, threads_count):
                """Worker function to render a single chunk."""
                try:
                    # Apply Fades (Stateful modification, must happen here or before)
                    # Note: We passed the configured clip.
                    
                    # RENDER PART (VIDEO ONLY)
                    logger.info(f"[Worker-{idx}] Rendering video part to {output_path}...")
                    
                    video_clip.write_videofile(
                        output_path, 
                        fps=24, 
                        codec='libx264',
                        audio=False, 
                        preset='ultrafast',
                        threads=threads_count, # Distributed threads
                        logger=None
                    )
                    
                    # Return metadata about the part
                    return {
                        "file": output_path,
                        "pad_head": task.get("pad_head", 0.0),
                        "pad_tail": task.get("pad_tail", 0.0),
                        "is_block_start": task["is_block_start"],
                        "block_index": task["block_index"],
                        "chunk_index": idx
                    }
                except Exception as e:
                    logger.error(f"[Worker-{idx}] Error: {e}")
                    raise e
                finally:
                    # CLEANUP inside worker to ensure it closes after use
                    try:
                        video_clip.close()
                    except: pass
                    
            
            batch_start_time = time.time()
            futures = []
            
            # We must maintain order of 'part_files' eventually, or sort them later.
            # We also need to throttle creation of clips to avoid opening 1000 files.
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                for idx, task in enumerate(render_tasks):
                    # Check existing futures
                    # If we have too many pending, wait for one to finish
                    while len(futures) >= MAX_WORKERS * 2: # buffer a bit
                        done, not_done = concurrent.futures.wait(futures, return_when=concurrent.futures.FIRST_COMPLETED)
                        # Process done futures to catch errors early
                        for f in done:
                            if f.exception():
                                raise f.exception()
                        futures = list(not_done)
                    
                    current_time = time.time()
                    elapsed = current_time - batch_start_time
                    
                    msg = f"Batch {i+1}: Preparing part {idx+1}/{len(render_tasks)} | Elapsed: {elapsed:.1f}s"
                    if progress_callback and idx % 5 == 0:
                        progress_callback(0.2 + 0.6 * (idx / len(render_tasks)), msg)

                    speed_factor = task.get("speed", 1.0)
                    logger.info(f"[Batch {i+1}] Preparing Chunk {idx+1}/{len(render_tasks)} (Speed: {speed_factor}x)")
                    
                    chunk_start = task["start"]
                    chunk_end = task["end"]
                    duration = task["duration"]
                    folder = task["folder"]
                    speed_factor = task.get("speed", 1.0)
                    
                    # TRANSITION LOGIC
                    pad_head = 0.0
                    pad_tail = 0.0
                    
                    has_trans = config.transition_type != "None" and config.transition_type != "无"
                    trans_dur = config.transition_duration
                    
                    if has_trans and task["is_block_start"] and task["block_index"] > 0:
                        if config.transition_type == "Crossfade":
                            pad_head = trans_dur
                            
                    if has_trans and task["is_block_end"] and task["block_index"] < task["total_blocks"] - 1:
                        if config.transition_type == "Crossfade":
                            pad_tail = trans_dur
                    
                    # Inject pads into task for worker
                    task["pad_head"] = pad_head
                    task["pad_tail"] = pad_tail
                    
                    # The duration we NEED (in final video time)
                    needed_duration = duration + pad_head + pad_tail
                    
                    # The duration we FETCH from source (raw time)
                    # The duration we FETCH from source (raw time)
                    # If speed is 2.0 (faster), we need 2x source material to fill the time.
                    # If speed is 0.5 (slower), we need 0.5x source material.
                    fetch_duration_source = needed_duration * speed_factor
                    
                    # Random Cut Params (default to 0 if not set)
                    clip_min = task.get("clip_min_duration", 0.0)
                    clip_max = task.get("clip_max_duration", 0.0)
                    
                    # Get Video Clip (Main Thread - SAFE)
                    video_clip = None
                    try:
                        if folder:
                            # Decide between Random Cuts vs Ordered Stream
                            if clip_min > 0.1 and clip_max > clip_min:
                                # Use Random Cuts
                                # Note: get_random_cut_clip returns a concatenated clip of random parts
                                video_clip, segment_meta = self.matcher.get_random_cut_clip(
                                    folder, 
                                    fetch_duration_source, 
                                    clip_min * speed_factor, # Scale limits to source time? No, usually limits are visual. 
                                    # Wait. A 2s visual clip at 2x speed needs 4s source.
                                    # So min_dur/max_dur should be SCALED if we apply speed AFTER.
                                    # Actually get_random_cut_clip assembles SOURCE clips.
                                    # If we want final visual clip to be 2-4s:
                                    # Source clip needs to be 4-8s (at 2x speed).
                                    # So we pass scaled limits.
                                    clip_max * speed_factor
                                )
                            else:
                                # Use Ordered Stream
                                video_clip, segment_meta = self.matcher.get_ordered_clip(folder, fetch_duration_source)
                            
                            if video_clip:
                                batch_metadata.append({
                                    "chunk_index": idx,
                                    "timeline_start": chunk_start,
                                    "timeline_end": chunk_end,
                                    "segments": segment_meta,
                                    "transition_pad_head": pad_head,
                                    "transition_pad_tail": pad_tail,
                                    "speed_factor": speed_factor
                                })
                        
                        if not video_clip:
                             logger.warning(f"No video found for chunk {idx}, using placeholder.")
                             video_clip = ColorClip(size=(config.width, config.height), color=(0,0,0), duration=needed_duration)
                        else:
                            # Resize/Crop
                            video_clip = self.matcher.resize_and_crop(video_clip, (config.width, config.height))
                            
                            # Apply Speed Effect if needed
                            if abs(speed_factor - 1.0) > 0.01:
                                video_clip = video_clip.fx(speedx, speed_factor)
                        
                        # Ensure exact duration (trim floating point errors or excess fetch)
                        video_clip = video_clip.set_duration(needed_duration)
                        
                        # Apply Fade Effects (CPU bound, fast)
                        if config.transition_type == "Fade to Black":
                             if task["is_block_start"] and task["block_index"] > 0:
                                 video_clip = video_clip.fadein(trans_dur)
                             if task["is_block_end"] and task["block_index"] < task["total_blocks"] - 1:
                                 video_clip = video_clip.fadeout(trans_dur)
                        
                        part_file = os.path.join(temp_parts_dir, f"part_{idx:04d}.mp4")
                        
                        # Submit to Worker
                        future = executor.submit(render_chunk_worker, idx, task, video_clip, part_file, THREADS_PER_JOB)
                        futures.append(future)
                        
                    except Exception as e:
                        logger.error(f"Error preparing chunk {idx}: {e}")
                        raise e

                # Wait for all remaining
                for f in concurrent.futures.as_completed(futures):
                    res = f.result()
                    # We can append here, but order might be scrambled.
                    # We used 'idx' in filename so we can sort later or store in dict.
                    pass
            
            logger.info("All chunks rendered. Collecting results...")
            
            # Reconstruct ordered list
            # We can re-scan the dir or build from futures if we tracked them.
            # Simpler: Scan dir based on known pattern.
            part_files = []
            for idx in range(len(render_tasks)):
                 part_file = os.path.join(temp_parts_dir, f"part_{idx:04d}.mp4")
                 # We need the metadata we computed (pad_head/tail).
                 # We can re-compute or store it in a map 'chunk_meta_map'.
                 # Actually, we can just grab it from 'render_tasks' using the modified task object?
                 # No, 'render_tasks' was local.
                 # Let's re-calculate logic briefly is safer or retrieve from where?
                 # We modified 'task' dict in the loop. 'render_tasks' contains those modified dicts!
                 t = render_tasks[idx] 
                 part_files.append({
                        "file": part_file,
                        "pad_head": t.get("pad_head", 0.0),
                        "pad_tail": t.get("pad_tail", 0.0),
                        "is_block_start": t["is_block_start"],
                        "block_index": t["block_index"]
                 })
                 
            import gc
            gc.collect()

            # Concatenate Parts
            if not part_files:
                continue
                
            logger.info(f"All chunks rendered. Concatenating {len(part_files)} parts...")
            
            # Determine if we can use Fast Path (Direct FFmpeg Concat)
            # We can use fast path if Config is NOT Crossfade.
            # Fade to Black and None are baked into chunks, so linear concat works.
            use_fast_path = (config.transition_type != "Crossfade")
            
            # --- START SUBTITLE PREPARATION (Common) ---
            # Prepare subtitle filter args
            # Use forward slashes and ensure absolute path for filter
            srt_abspath = os.path.abspath(srt_path)
            
            if not os.path.exists(srt_abspath):
                 logger.error(f"CRITICAL: SRT file does NOT exist at {srt_abspath}")
            
            # Default to original
            final_srt_path = srt_abspath
            
            # Offset Logic
            SHIFT_SECONDS = -0.5
            try:
                # Check if we already shifted? Only do it once or unique per batch?
                # Ideally we do it once per run, but we are in a loop.
                # To avoid re-shifting multiple times if we reused srt_path, 
                # we should check if we already created a shifted file.
                shifted_srt_name = f"shifted_{os.path.basename(srt_path)}"
                shifted_srt_path = os.path.join(batch_dir, shifted_srt_name)
                
                if not os.path.exists(shifted_srt_path):
                    logger.info(f"Applying {SHIFT_SECONDS}s shift to subtitles...")
                    subs_obj = pysrt.open(srt_abspath)
                    subs_obj.shift(seconds=SHIFT_SECONDS)
                    subs_obj.save(shifted_srt_path, encoding='utf-8')
                
                final_srt_path = os.path.abspath(shifted_srt_path)
            except Exception as e:
                logger.error(f"Error shifting subtitles: {e}")

            # Path formatting for FFmpeg 'subtitles' filter
            srt_filter_path = final_srt_path.replace('\\', '/')
            if os.name == 'nt':
                srt_filter_path = srt_filter_path.replace(':', '\\:')
            
            # Subtitle Style
            def hex_to_ass(hex_color):
                c = hex_color.lstrip('#')
                if len(c) == 6:
                    r, g, b = c[0:2], c[2:4], c[4:6]
                    return f"&H00{b}{g}{r}".upper()
                return "&H00FFFFFF"

            primary_color_ass = hex_to_ass(config.subtitle_color)
            font_name_escaped = config.subtitle_font_name.replace(" ", r"\ ")
            
            style_str = (
                f"Fontname={font_name_escaped},FontSize={config.subtitle_font_size},"
                f"PrimaryColour={primary_color_ass},Outline={config.subtitle_outline},"
                f"Shadow={config.subtitle_shadow},MarginV={config.subtitle_margin_v},"
                f"Alignment=2,Bold={1 if config.subtitle_bold else 0}"
            )
            
            ffmpeg_sub_filter = f"subtitles='{srt_filter_path}':force_style='{style_str}'"
            # --- END SUBTITLE PREPARATION ---

            output_filename = os.path.join(batch_dir, f"batch_{i+1}.mp4")
            logger.info(f"Saving Final Video to {output_filename}")


            if use_fast_path:
                logger.info(">>> FAST PATH ACTIVATED: Using Direct FFmpeg Concatenation <<<")
                
                # 1. Generate Concat List
                concat_list_path = os.path.join(batch_dir, f"concat_list_{i}.txt")
                with open(concat_list_path, 'w', encoding='utf-8') as f:
                    for p_info in part_files:
                        # ffmpeg requires forward slashes and safe paths
                        p_abs = os.path.abspath(p_info["file"]).replace('\\', '/')
                        f.write(f"file '{p_abs}'\n")
                
                # 2. Prepare Audio (Mix in Python, export to temp)
                # This ensures we get specific BGM looping and volume correct without complex ffmpeg filters
                if progress_callback:
                    progress_callback(0.85, f"Batch {i+1}: Mixing Audio...")
                    
                temp_audio_path = os.path.join(batch_dir, f"temp_audio_{i}.m4a")
                
                try:
                    # Main Audio
                    final_audio_clip = main_audio
                    
                    # Add BGM if needed
                    if config.bgm_file:
                        bgm_path = os.path.join(self.assets_dir, "bgm", config.bgm_file)
                        if os.path.exists(bgm_path):
                             from moviepy.audio.fx.all import audio_loop, volumex
                             bgm_clip = AudioFileClip(bgm_path)
                             # Calculate duration from parts
                             total_vid_dur = sum(p["pad_head"] + p.get("duration",0) + p["pad_tail"] for p in render_tasks)
                             # No, easier: Use main_audio duration
                             target_dur = main_audio.duration
                             bgm_clip = audio_loop(bgm_clip, duration=target_dur)
                             bgm_clip = bgm_clip.fx(volumex, 0.3)
                             final_audio_clip = CompositeAudioClip([main_audio, bgm_clip])
                    
                    # Write Temp Audio
                    # Explicitly use 'aac' to avoid libfdk_aac dependency issues
                    final_audio_clip.write_audiofile(temp_audio_path, logger=None, fps=44100, codec='aac')
                    
                    # 3. Run FFmpeg
                    if progress_callback:
                        progress_callback(0.95, f"Batch {i+1}: Final FFmpeg Encoding...")
                    
                    import subprocess
                    
                    # Check if text file exists
                    if not os.path.exists(concat_list_path):
                        raise RuntimeError("Concat list file missing!")

                    cmd = [
                        "ffmpeg", "-y",
                        "-f", "concat",
                        "-safe", "0",
                        "-i", concat_list_path,
                        "-i", temp_audio_path,
                        "-vf", ffmpeg_sub_filter,
                        "-c:v", "libx264",
                        "-preset", "ultrafast",
                        "-c:a", "aac",
                        "-threads", str(render_threads),
                        "-map", "0:v",
                        "-map", "1:a",
                        "-shortest", # Finish when shortest input ends (usually audio)
                        output_filename
                    ]
                    
                    logger.info(f"Running FFmpeg: {' '.join(cmd)}")
                    
                    # Run Command
                    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    stdout, stderr = process.communicate()
                    
                    if process.returncode != 0:
                        logger.error(f"FFmpeg Error: {stderr}")
                        raise RuntimeError("FFmpeg encoding failed.")
                    else:
                        logger.info("FFmpeg Fast Path Complete.")
                        generated_files.append(output_filename)
                        
                except Exception as e:
                     logger.error(f"Fast Path Failed: {e}. Falling back to standard method.")
                     use_fast_path = False
                     # Fallback proceeds below...

            if not use_fast_path:
                # --- STANDARD MOVIEPY PATH (Legacy/Complex) ---
                logger.info("Using Standard MoviePy Assembly (Slow Path)...")

                # Load all parts
                clip_objects = []
                # ... (Existing logic for logical_blocks) ...
                try:
                    # 1. Load all physical file parts
                    loaded_parts = []
                    for idx, p_info in enumerate(part_files):
                        c = VideoFileClip(p_info["file"])
                        loaded_parts.append({
                            "clip": c,
                            "block_index": p_info["block_index"],
                            "chunk_index": idx
                        })
                    
                    # 2. Group parts into "Logical Blocks" (Scenes)
                    logical_blocks = []
                    current_group = []
                    current_blk_idx = -1
                    
                    for item in loaded_parts:
                        if item["block_index"] != current_blk_idx:
                            if current_group:
                                # Concat previous group into one Block Clip
                                if len(current_group) == 1:
                                    logical_blocks.append(current_group[0])
                                else:
                                    logical_blocks.append(concatenate_videoclips(current_group, method="compose"))
                            
                            current_group = []
                            current_blk_idx = item["block_index"]
                        
                        current_group.append(item["clip"])
                    
                    # Append last group
                    if current_group:
                        if len(current_group) == 1:
                            logical_blocks.append(current_group[0])
                        else:
                            logical_blocks.append(concatenate_videoclips(current_group, method="compose"))
                            
                    logger.info(f"Assembled {len(logical_blocks)} logical blocks (scenes).")

                    # 3. Apply Transitions between Logical Blocks
                    if config.transition_type == "Crossfade" and len(logical_blocks) > 1:
                        logger.info(f"Applying CROSSFADE (Duration: {config.transition_duration}s)...")
                        
                        # We need to apply .crossfadein() to blocks 1..N
                        processed_blocks = []
                        # Keep first block as is
                        processed_blocks.append(logical_blocks[0])
                        
                        for i in range(1, len(logical_blocks)):
                            blk = logical_blocks[i]
                            blk = blk.crossfadein(config.transition_duration)
                            processed_blocks.append(blk)
                        
                        # Concat with overlap
                        # padding should be negative duration
                        final_video_visual = concatenate_videoclips(
                            processed_blocks, 
                            method="compose", 
                            padding= -config.transition_duration
                        )
                    else:
                        logger.info(f"Concatenating blocks linearly (Method: Chain). (Config Type: '{config.transition_type}')")
                        final_video_visual = concatenate_videoclips(logical_blocks, method="chain")
                    
                    # Set Audio
                    if progress_callback:
                        progress_callback(0.85, f"Batch {i+1}: Assembling & syncing audio...")
                    
                    final_duration = main_audio.duration
                    if final_video_visual.duration > final_duration + 1.0: # Allow slight slack
                         logger.warning(f"Video ({final_video_visual.duration:.2f}s) > Audio ({final_duration:.2f}s). Clipping video.")
                         final_video_visual = final_video_visual.subclip(0, final_duration)
                    elif final_video_visual.duration < final_duration:
                         logger.warning(f"Video ({final_video_visual.duration}s) < Audio ({final_duration}s). Padding video (or letting it hold).")
                         final_video_visual = final_video_visual.set_duration(final_duration)
                         
                    final_video = final_video_visual.set_audio(main_audio)
                    
                    # Add BGM
                    if config.bgm_file:
                        bgm_path = os.path.join(self.assets_dir, "bgm", config.bgm_file)
                        if os.path.exists(bgm_path):
                            from moviepy.audio.fx.all import audio_loop, volumex
                            bgm_clip = AudioFileClip(bgm_path)
                            bgm_clip = audio_loop(bgm_clip, duration=final_video.duration)
                            bgm_clip = bgm_clip.fx(volumex, 0.3)
                            final_audio = CompositeAudioClip([final_video.audio, bgm_clip])
                            final_video = final_video.set_audio(final_audio)

                    logger.info("This step includes FFmpeg encoding and burning subtitles. Please wait...")

                    if progress_callback:
                        progress_callback(0.95, f"Batch {i+1}: Encoding final video (this may take a while)...")
                    
                    ffmpeg_params = [
                        '-vf', 
                        ffmpeg_sub_filter # Reusing the filter string prepared above
                    ]
                    logger.info(f"Final ffmpeg_params: {ffmpeg_params}")
                    
                    # Write file
                    final_video.write_videofile(
                        output_filename, 
                        fps=24, 
                        codec='libx264', 
                        audio_codec='aac',
                        threads=render_threads,
                        preset='ultrafast',
                        logger=None,
                        ffmpeg_params=ffmpeg_params
                    )
                    logger.info(f"Video encoding finished: {output_filename}")
                    generated_files.append(output_filename)

                finally:
                    # Close clips logic handled in global finally block usually, 
                    # but here we should close local clips if we opened them in this block
                    pass
                
                # --- END STANDARD PATH ---

            # Save Metadata
            meta_filename = output_filename.replace('.mp4', '_metadata.json')
                

            try:
                with open(meta_filename, 'w', encoding='utf-8') as f:
                    json.dump(batch_metadata, f, indent=2, ensure_ascii=False)
                logger.info(f"Metadata saved to {meta_filename}")
            except Exception as e:
                logger.error(f"Error saving metadata: {e}")
                
            finally:
                # Close all clips
                if 'final_clips' in locals():
                    for c in final_clips:
                        try: c.close()
                        except: pass
                if 'clip_objects' in locals() and clip_objects:
                     for c in clip_objects:
                        try: c.close() 
                        except: pass
                        
                if 'final_video' in locals(): final_video.close()
                if 'main_audio' in locals(): main_audio.close()

        # Cleanup shared resources


        return generated_files
