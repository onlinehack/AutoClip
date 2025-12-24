import random
import os
from typing import List, Dict, Optional
from moviepy.editor import VideoFileClip, vfx, concatenate_videoclips
from src.models import FolderWeight
from src.utils import get_video_files

class Matcher:
    def __init__(self, assets_dir: str):
        self.assets_dir = assets_dir
        # folder_path -> { 'videos': [], 'current_vid_idx': 0, 'current_time': 0.0 }
        self.folder_states = {}

    def _init_folder_state(self, folder_path: str):
        if folder_path not in self.folder_states:
            videos = sorted(get_video_files(folder_path)) # Sort by name
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
                # In a persistent app, we might cache these objects, but here we just open/close.
                full_clip = VideoFileClip(video_path)
                video_len = full_clip.duration
                
                start_t = state['current_time']
                
                # Check if we can take the full remainder from this video
                available_time = video_len - start_t
                
                if available_time <= 0:
                    # Current video finished exactly or we overshot?
                    # Move to next video
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
                
                # Update State
                state['current_time'] += take_time
                remaining_duration -= take_time
                
                # If we finished this video, set up next
                if state['current_time'] >= video_len - 0.1: # Threshold
                    state['current_vid_idx'] = (state['current_vid_idx'] + 1) % len(videos)
                    state['current_time'] = 0.0
                    
            except Exception as e:
                print(f"Error reading video {video_path}: {e}")
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
        clip = clip.resize(scale_factor)
            
        # Center crop
        # Note: clip.w and clip.h are updated after resize
        clip = clip.crop(width=target_w, height=target_h, x_center=clip.w/2, y_center=clip.h/2)
        
        return clip

