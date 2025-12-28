import random
import os
from typing import List, Dict, Optional
from moviepy.editor import VideoFileClip, vfx, concatenate_videoclips
from src.models import FolderWeight
from src.utils import get_video_files
from src.logger import setup_logger

logger = setup_logger("Matcher")

class Matcher:
    def __init__(self, assets_dir: str):
        self.assets_dir = assets_dir
        # folder_path -> { 'videos': [], 'current_vid_idx': 0, 'current_time': 0.0 }
        self.folder_states = {}

    def _init_folder_state(self, folder_path: str):
        if folder_path not in self.folder_states:
            videos = sorted(get_video_files(folder_path)) # Sort by name
            logger.info(f"Initialized folder: {os.path.basename(folder_path)} | Found {len(videos)} videos.")
            self.folder_states[folder_path] = {
                'videos': videos,
                'current_vid_idx': 0,
                'current_time': 0.0
            }

    def get_ordered_clip(self, folder_path: str, target_duration: float):
        """
        Get the next chunk of video from the folder's sequence.
        Seamlessly transitions to the next video if the current one ends.
        """
        self._init_folder_state(folder_path)
        state = self.folder_states[folder_path]
        videos = state['videos']
        
        if not videos:
            return None

        clips_to_concat = []
        segments_used = []
        remaining_duration = target_duration

        # Prevent infinite loops if all videos are broken or 0 duration (safety break)
        loop_guard = 0
        max_loops = len(videos) * 2

        while remaining_duration > 0 and loop_guard < max_loops:
            video_path = videos[state['current_vid_idx']]
            try:
                # Load clip efficiently? Warning: VideoFileClip can be slow if opened repeatedly
                # But we need duration.
                logger.info(f"Loading source video: {os.path.basename(video_path)} (Idx: {state['current_vid_idx']})")
                # In a persistent app, we might cache these objects, but here we just open/close.
                full_clip = VideoFileClip(video_path)
                video_len = full_clip.duration
                
                start_t = state['current_time']
                
                # Check if we can take the full remainder from this video
                available_time = video_len - start_t
                
                if available_time <= 0:
                    # Current video finished exactly or we overshot?
                    # Move to next video
                    logger.info("Video finished (Exact/Over). Moving to next.")
                    state['current_vid_idx'] = (state['current_vid_idx'] + 1) % len(videos)
                    state['current_time'] = 0.0
                    full_clip.close() 
                    loop_guard += 1
                    continue
                
                take_time = min(available_time, remaining_duration)
                
                sub = full_clip.subclip(start_t, start_t + take_time)
                clips_to_concat.append(sub)
                
                segments_used.append({
                    "source_file": video_path,
                    "source_start": start_t,
                    "source_end": start_t + take_time,
                    "duration": take_time
                })
                
                logger.info(f"Selected segment: {take_time:.2f}s from {start_t:.2f}s to {start_t + take_time:.2f}s")
                
                # Update State
                state['current_time'] += take_time
                remaining_duration -= take_time
                
                # If we finished this video, set up next
                if state['current_time'] >= video_len - 0.1: # Threshold
                    state['current_vid_idx'] = (state['current_vid_idx'] + 1) % len(videos)
                    state['current_time'] = 0.0
                    
            except Exception as e:
                logger.error(f"Error reading video {video_path}: {e}")
                # Skip to next video on error
                state['current_vid_idx'] = (state['current_vid_idx'] + 1) % len(videos)
                state['current_time'] = 0.0
            
            loop_guard += 1

        if not clips_to_concat:
            return None, []
            
        if len(clips_to_concat) == 1:
            return clips_to_concat[0], segments_used
        else:
            return concatenate_videoclips(clips_to_concat), segments_used

    def get_random_cut_clip(self, folder_path: str, target_total_duration: float, min_dur: float, max_dur: float):
        """
        Randomly select multiple clips from folder to fill target_total_duration.
        Each clip length is between min_dur and max_dur.
        Does NOT maintain state (Pure Random).
        """
        self._init_folder_state(folder_path) # Just to load list
        state = self.folder_states[folder_path]
        videos = state['videos']
        
        if not videos:
            return None, []
            
        clips_to_concat = []
        segments_used = []
        current_len = 0.0
        
        # Local cache to prevent opening the same file multiple times (OOM prevention)
        # path -> VideoFileClip
        local_clip_cache = {}
        
        # Max retries to prevent infinite loop
        safety_break = 0

        while current_len < target_total_duration and safety_break < 100:
            remaining = target_total_duration - current_len
            
            this_dur = random.uniform(min_dur, max_dur)
            
            if this_dur > remaining:
                this_dur = remaining
            elif remaining - this_dur < 1.0: 
                this_dur = remaining
                
            if this_dur <= 0.05: 
                break
                
            vid_path = random.choice(videos)
            
            try:
                # CACHING LOGIC
                if vid_path in local_clip_cache:
                    temp_clip = local_clip_cache[vid_path]
                else:
                    # Open and cache
                    temp_clip = VideoFileClip(vid_path)
                    local_clip_cache[vid_path] = temp_clip
                
                vid_len = temp_clip.duration
                
                if vid_len < this_dur:
                    # If video is too short, we skip it or take all
                    # For stability, let's just skip very short videos in random mode
                    # unless it's the only option? No, we have a list.
                    if vid_len < 0.5:
                        safety_break += 1
                        continue
                    
                    # Take what we can? 
                    # If we need 2s but video is 1s.
                    # Let's just find another one.
                    safety_break += 1
                    continue
                else:
                    max_start = vid_len - this_dur
                    start_t = random.uniform(0, max_start)
                    
                    sub = temp_clip.subclip(start_t, start_t + this_dur)
                    actual_dur = this_dur
                
                clips_to_concat.append(sub)
                segments_used.append({
                    "source_file": vid_path,
                    "source_start": start_t,
                    "source_end": start_t + actual_dur,
                    "duration": actual_dur,
                    "is_random_cut": True
                })
                
                current_len += actual_dur
                logger.info(f"Random cut: {os.path.basename(vid_path)} [{start_t:.2f}s - {start_t + actual_dur:.2f}s] (Dur: {actual_dur:.2f}s) | Progress: {current_len:.1f}/{target_total_duration:.1f}")
                
            except Exception as e:
                logger.error(f"Error reading {vid_path}: {e}")
                safety_break += 1
        
        if not clips_to_concat:
            # Clean up cache if failed
            for c in local_clip_cache.values():
                try: c.close()
                except: pass
            return None, []
            
        if len(clips_to_concat) == 1:
            # We must NOT close the clip because it's being returned.
            # But we should close others in cache if they were unused (unlikely logic path here but good practice)
            # Actually, return the clip. The caller (Worker) will close it.
            # BUT, the clip is typically a subclip. Does closing subclip close the master in local_clip_cache?
            # Issue: accessing subclip after master is closed fails.
            # So we must keep masters alive.
            # We attach the cache to the clip so it survives until clip is garbage collected/closed?
            res_clip = clips_to_concat[0]
            res_clip.sources_cache = local_clip_cache # Hack to keep RefCount > 0
            return res_clip, segments_used
        else:
            # Concatenate
            # method='compose' is safer for mixed formats. 'chain' is faster but fragile.
            # Given we resized? No, we haven't resized yet! Matcher just returns raw clips. 
            # Resize happens in Pipeline.
            # So sources might have different resolutions!
            # concatenate_videoclips with method='compose' handles resolution mismatch (scales to biggest).
            # But we prefer uniform resize later. 
            # If we return a composite, Pipeline will resize the composite.
            
            final_clip = concatenate_videoclips(clips_to_concat, method="compose")
            final_clip.sources_cache = local_clip_cache # Keep masters alive
            return final_clip, segments_used

    def resize_and_crop(self, clip: VideoFileClip, target_size: tuple) -> VideoFileClip:
        """
        Resize and center crop the clip to fill target_size.
        Uses scalar scaling to strictly preserve aspect ratio.
        """
        w, h = clip.size
        target_w, target_h = target_size
        
        # Optimization: Skip if dimensions exactly match
        if w == target_w and h == target_h:
            return clip
        
        # Calculate scale factor needed to cover the target area
        scale_factor = max(target_w / w, target_h / h)
        
        # Resize using a single scalar to strictly preserve aspect ratio
        # print(f"[{datetime.now()}] [Matcher] Resizing clip from {w}x{h} to target {target_w}x{target_h} (Scale: {scale_factor:.4f})")
        clip = clip.resize(scale_factor)
            
        # Center crop
        # Note: clip.w and clip.h are updated after resize
        clip = clip.crop(width=target_w, height=target_h, x_center=clip.w/2, y_center=clip.h/2)
        
        return clip

