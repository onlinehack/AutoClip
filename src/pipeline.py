import os
import time
from datetime import datetime
from typing import List
from moviepy.editor import concatenate_videoclips, AudioFileClip, CompositeVideoClip, CompositeAudioClip

from src.models import MixConfig
from src.utils import split_text
from src.processors.tts import run_tts_sync
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
        
        sentences = split_text(config.text)
        # We need a temp dir that persists across the batch to hold all audio first?
        # Actually logic is per-video (batch_count). For each video, we do the narrative.
        
        generated_files = []

        for i in range(config.batch_count):
            temp_dir = os.path.join(batch_dir, "temp", f"batch_{i}")
            os.makedirs(temp_dir, exist_ok=True)

            if progress_callback:
                progress_callback(0.1, f"Batch {i+1}: Generating Audio...")

            # 1. Generate ALL Audio First to get Total Duration
            audio_segments = [] # List of (audio_path, duration, sentence_text)
            total_duration = 0.0
            
            for idx, sentence in enumerate(sentences):
                tts_file = os.path.join(temp_dir, f"tts_{idx}.mp3")
                try:
                    run_tts_sync(sentence, config.voice, tts_file)
                    # Verify file exists
                    if not os.path.exists(tts_file) or os.path.getsize(tts_file) == 0:
                         print(f"Warning: TTS failed for '{sentence[:10]}...', skipping.")
                         continue
                         
                    ac = AudioFileClip(tts_file)
                    dur = ac.duration
                    audio_segments.append({
                        "path": tts_file,
                        "duration": dur,
                        "text": sentence,
                        "clip": ac
                    })
                    total_duration += dur
                except Exception as e:
                     print(f"Error generating TTS for segment {idx}: {e}")

            if not audio_segments:
                raise ValueError("No audio segments generated. Check TTS or text input.")

            # 2. Plan Strategy (Timeline)
            # Allocation of time per folder based on weights
            # We treat weights as "Blocks" in order.
            # E.g. A=50, B=50. Total 100s. -> A gets 50s, B gets 50s.
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

            # 3. Assemble Video
            clips = []
            elapsed_time = 0.0
            
            for idx, seg in enumerate(audio_segments):
                if progress_callback:
                    progress_callback(0.2 + 0.7 * (idx / len(audio_segments)), f"Batch {i+1}: Processing visual {idx+1}/{len(audio_segments)}")

                seg_start = elapsed_time
                seg_end = elapsed_time + seg["duration"]
                
                # Determine which folder owns this segment (based on mid-point or start)
                # Using mid-point is safer
                mid_point = (seg_start + seg_end) / 2
                
                selected_folder = None
                for block in timeline_blocks:
                    if block["start"] <= mid_point < block["end"]:
                        selected_folder = block["folder"]
                        break
                
                # Fallback to last folder if somehow out of bounds
                if not selected_folder and timeline_blocks:
                     selected_folder = timeline_blocks[-1]["folder"]
                
                if not selected_folder:
                     raise ValueError("No folder selected for segment. Check weights.")
                     
                print(f"DEBUG: Segment {idx} ({seg_start:.1f}-{seg_end:.1f}s) assigned to {os.path.basename(selected_folder)}")

                # Get Video Chunk (Sequential)
                video_clip = self.matcher.get_ordered_clip(selected_folder, seg["duration"])
                
                if not video_clip:
                     # Fallback? Create color clip?
                     print(f"Warning: No video found in {selected_folder}.")
                     # Make a black placeholder
                     from moviepy.editor import ColorClip
                     video_clip = ColorClip(size=(config.width, config.height), color=(0,0,0), duration=seg['duration'])
                else:
                     # Resize/Crop
                     video_clip = self.matcher.resize_and_crop(video_clip, (config.width, config.height))
                
                # Composite
                video_clip = video_clip.set_audio(seg["clip"])
                subtitle_clip = create_subtitle_clip(
                    seg["text"], 
                    duration=seg["duration"], 
                    size=(config.width, config.height)
                )
                
                final_clip = CompositeVideoClip([video_clip, subtitle_clip])
                clips.append(final_clip)
                
                elapsed_time += seg["duration"]

            # Concatenate
            final_video = concatenate_videoclips(clips)
            
            # Add BGM
            if config.bgm_file:
                bgm_path = os.path.join(self.assets_dir, "bgm", config.bgm_file)
                if os.path.exists(bgm_path):
                    from moviepy.audio.fx.all import audio_loop
                    bgm_clip = AudioFileClip(bgm_path)
                    bgm_clip = audio_loop(bgm_clip, duration=final_video.duration)
                    bgm_clip = bgm_clip.volumex(0.3)
                    final_audio = CompositeAudioClip([final_video.audio, bgm_clip])
                    final_video = final_video.set_audio(final_audio)

            output_filename = os.path.join(batch_dir, f"batch_{i+1}.mp4")
            final_video.write_videofile(output_filename, fps=24, codec='libx264', audio_codec='aac')
            generated_files.append(output_filename)

        return generated_files
