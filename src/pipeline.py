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
        
        # CPU Optimization for Xeon/High-core CPUs
        # Detected cores or default to 16 if retrieval fails
        cpu_cores = os.cpu_count() or 16
        # Limit threads to reasonable max for FFmpeg (usually diminishing returns > 32, but let's allow up to 32 or full usage)
        # For Xeon, using all cores is generally desired.
        render_threads = max(4, cpu_cores)
        print(f"[{datetime.now()}] [Pipeline] Multi-core Optimization: Using {render_threads} threads for encoding.")
        
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
            
            for idx_b, block in enumerate(timeline_blocks):
                b_start = block["start"]
                b_end = block["end"]
                folder = block["folder"]
                
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
            
            # Heuristic: 
            # - Xeon has many cores. 
            # - FFmpeg efficient up to ~8-16 threads.
            # - Too many parallel FFmpeg instances choke IO.
            # Strategy: 4 parallel renders, each using (Cores/4) threads.
            MAX_WORKERS = max(1, cpu_cores // 4)
            if MAX_WORKERS > 4: MAX_WORKERS = 4 # Cap at 4 parallel encodes to avoid IO thrashing
            
            THREADS_PER_JOB = max(2, cpu_cores // MAX_WORKERS)
            
            print(f"[{datetime.now()}] [Pipeline] Parallel Rendering: {MAX_WORKERS} workers, {THREADS_PER_JOB} threads/worker.")
            
            def render_chunk_worker(idx, task, video_clip, output_path, threads_count):
                """Worker function to render a single chunk."""
                try:
                    # Apply Fades (Stateful modification, must happen here or before)
                    # Note: We passed the configured clip.
                    
                    # RENDER PART (VIDEO ONLY)
                    print(f"[{datetime.now()}] [Worker-{idx}] Rendering video part to {output_path}...")
                    
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
                    print(f"[{datetime.now()}] [Worker-{idx}] Error: {e}")
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

                    print(f"[{datetime.now()}] [Pipeline] [Batch {i+1}] Preparing Chunk {idx+1}/{len(render_tasks)}")
                    
                    chunk_start = task["start"]
                    chunk_end = task["end"]
                    duration = task["duration"]
                    folder = task["folder"]
                    
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
                    
                    fetch_duration = duration + pad_head + pad_tail
                    
                    # Get Video Clip (Main Thread - SAFE)
                    video_clip = None
                    try:
                        if folder:
                            # print(f"[{datetime.now()}] [Pipeline] Searching clip...")
                            video_clip, segment_meta = self.matcher.get_ordered_clip(folder, fetch_duration)
                            
                            if video_clip:
                                batch_metadata.append({
                                    "chunk_index": idx,
                                    "timeline_start": chunk_start,
                                    "timeline_end": chunk_end,
                                    "segments": segment_meta,
                                    "transition_pad_head": pad_head,
                                    "transition_pad_tail": pad_tail
                                })
                        
                        if not video_clip:
                             print(f"[{datetime.now()}] Warning: No video found for chunk {idx}, using placeholder.")
                             video_clip = ColorClip(size=(config.width, config.height), color=(0,0,0), duration=fetch_duration)
                        else:
                            video_clip = self.matcher.resize_and_crop(video_clip, (config.width, config.height))
                        
                        video_clip = video_clip.set_duration(fetch_duration)
                        
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
                        print(f"[{datetime.now()}] Error preparing chunk {idx}: {e}")
                        raise e

                # Wait for all remaining
                for f in concurrent.futures.as_completed(futures):
                    res = f.result()
                    # We can append here, but order might be scrambled.
                    # We used 'idx' in filename so we can sort later or store in dict.
                    pass
            
            print(f"[{datetime.now()}] [Pipeline] All chunks rendered. Collecting results...")
            
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
                
            print(f"[{datetime.now()}] [Pipeline] All chunks rendered. Concatenating {len(part_files)} parts...")
            
            # Load all parts
            clip_objects = []
            try:
                # We need to construct the list carefully for Crossfade
                # If Crossfade, we need to apply crossfadein to clips that have pad_head > 0? 
                # Actually, concatenate_videoclips with negative padding simply overlaps them.
                # If Part A has tail padding (overlap) and Part B has head padding (overlap).
                # We simply concat them with padding = -overlap.
                # BUT, render_tasks might be disjointed (chunks). We only want negative padding at Block Boundaries.
                
                # Logic:
                # 1. Iterate parts.
                # 2. If part is Start of Block (and not first block), it means previous part was End of Block.
                # 3. If config is Crossfade, we overlap them.
                
                # However, concatenate_videoclips takes a single list and a single 'padding' arg (if int/float).
                # If we provide a LIST of paddings to 'padding' arg? MoviePy docs say padding is float.
                # So we cannot mix hard cuts (chunks) and crossfades (blocks) easily with one call if we use simple padding.
                
                # WAITING: MoviePy `concatenate_videoclips` creates a CompositeVideoClip logic. 
                # Implementing complex transition per-clip requires manual composition or building a custom list.
                # EASIER METHOD:
                # Use `concatenate_videoclips` but apply `crossfadein` effect to the clip itself? 
                # `clip.crossfadein(d)` makes the clip fade in from the previous clip in the composite. 
                # It automatically handles the overlap logic when composed.
                # BUT, for `concatenate_videoclips`, we must enable `method='compose'` and likely pass padding.
                
                # If we cannot vary padding per clip in one call, we must chain them?
                # or use `method='chain'`? No, chain doesn't support overlap.
                
                # Let's try to set attributes on clips.
                
                final_clips = []
                for idx, p_info in enumerate(part_files):
                    c = VideoFileClip(p_info["file"])
                    
                    if config.transition_type == "Crossfade":
                        # If this clip is the start of a new block (and not the very first one)
                        # It should crossfade from the previous one.
                        # We also know we added `pad_head` to it.
                        
                        if p_info["is_block_start"] and p_info["block_index"] > 0:
                            # Apply crossfadein
                            # This causes MoviePy to expect an overlap
                            c = c.crossfadein(config.transition_duration)
                            
                        # Note: We rely on the fact that `concatenate_videoclips` with method='compose'
                        # will respect `c.start` which is adjusted by crossfadein?
                        # Actually no, `concatenate_videoclips` calculates start times sequentially.
                        # If a clip has `crossfadein(d)`, it effectively starts `d` seconds earlier relative to "end of prev".
                        # MoviePy source code suggests `concatenate_videoclips` handles `padding` globally.
                        
                        # ALTERNATIVE:
                        # We can manually set `start` times for a CompositeVideoClip.
                        # But that's hard.
                        
                        # LET'S USE A GLOBAL PADDING if we can?
                        # No, chunks inside a block have 0 padding.
                        
                        # TRICK:
                        # If we use `crossfadein`, `concatenate_videoclips(..., padding=None)` might not auto-overlap.
                # -------------------------------------------------------------------------
                # RE-ASSEMBLY LOGIC (Fixing Transition Issues)
                # -------------------------------------------------------------------------
                
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
                #    A Logical Block may consist of multiple file parts (chunks).
                #    Inside a block, parts are Hard Cut (they are just time segments).
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
                        
                print(f"[{datetime.now()}] [Pipeline] Assembled {len(logical_blocks)} logical blocks (scenes).")

                # 3. Apply Transitions between Logical Blocks
                if config.transition_type == "Crossfade" and len(logical_blocks) > 1:
                    print(f"[{datetime.now()}] [Pipeline] Applying CROSSFADE (Duration: {config.transition_duration}s)...")
                    
                    # We need to apply .crossfadein() to blocks 1..N
                    # And use negative padding during concat.
                    
                    # Note: logical_blocks[i] is now a Clip object (FileClip or CompositeClip)
                    
                    processed_blocks = []
                    # Keep first block as is
                    processed_blocks.append(logical_blocks[0])
                    
                    for i in range(1, len(logical_blocks)):
                        blk = logical_blocks[i]
                        # Apply crossfadein to the start of this block
                        # This works because we rendered EXTRA frames (Head Padding) for this block
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
                    # Hard Cut OR Fade to Black
                    # For Fade to Black, the effect is already "baked" into the pixels during render loop (fadein/out).
                    # So we just concat them linearly.
                    # Optimization: Use 'chain' instead of 'compose' for linear concatenation.
                    # 'chain' avoids the overhead of CompositeVideoClip frame blending logic.
                    print(f"[{datetime.now()}] [Pipeline] Concatenating blocks linearly (Method: Chain). (Config Type: '{config.transition_type}')")
                    final_video_visual = concatenate_videoclips(logical_blocks, method="chain")
                
                # Set Audio
                if progress_callback:
                    progress_callback(0.85, f"Batch {i+1}: Assembling & syncing audio...")
                
                final_duration = main_audio.duration
                if final_video_visual.duration > final_duration + 1.0: # Allow slight slack
                      # If video is way longer, it might be due to excess padding accumulation error?
                      # Or simply original strategy.
                      # We clip to audio.
                     print(f"[{datetime.now()}] Video ({final_video_visual.duration:.2f}s) > Audio ({final_duration:.2f}s). Clipping video.")
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
                    threads=render_threads,
                    preset='ultrafast', # <--- Major speedup
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
