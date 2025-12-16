import os
import math
from funasr import AutoModel

def format_time(ms):
    """Convert milliseconds to SRT timestamp format (HH:MM:SS,mmm)"""
    seconds = ms / 1000
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    seconds = seconds % 60
    milliseconds = int((seconds - int(seconds)) * 1000)
    return f"{hours:02d}:{minutes:02d}:{int(seconds):02d},{milliseconds:03d}"

def generate_srt(audio_file: str, output_srt: str) -> None:
    """
    Generate SRT file from audio using FunASR.
    """
    print(f"Loading FunASR model for {audio_file}...")
    try:
        model = AutoModel(
            model="paraformer-zh",
            vad_model="fsmn-vad",
            punc_model="ct-punc",
            log_level="ERROR"
        )
    except Exception as e:
        print(f"Error loading FunASR model: {e}")
        raise e
    
    print("Running inference...")
    try:
        res = model.generate(input=audio_file, batch_size_s=300)
    except Exception as e:
        print(f"Error running inference: {e}")
        raise e
    
    if not res:
        print("Warning: No result from ASR.")
        with open(output_srt, 'w', encoding='utf-8') as f:
            pass
        return

    # Use the first result
    entry = res[0]
    text = entry.get('text', '')
    timestamps = entry.get('timestamp', []) # List of [start, end] in ms

    if not text or not timestamps:
         print("Warning: Empty text or timestamps.")
         with open(output_srt, 'w', encoding='utf-8') as f:
            pass
         return
    
    # Logic to split by punctuation
    # We assume len(text) roughly equals len(timestamps) or we use the index.
    # Note: FunASR timestamps are for valid tokens. Punctuation might be inserted by punc_model and might not have timestamp.
    # We need to be careful.
    
    # Actually, punc_model inserts punctuation into 'text'. 'timestamp' corresponds to the acoustic tokens (characters without punctuation usually).
    # So len(text) >= len(timestamps).
    
    segments = []
    
    current_text = ""
    start_time = None
    end_time = None
    
    ts_idx = 0
    
    for char in text:
        current_text += char
        
        # Check if this char has a timestamp (is it a normal char?)
        # Simple heuristic: if it's not punctuation, consume a timestamp.
        # Punctuation list:
        full_puncs = "，。？！、；：,.?!;:"
        
        if char not in full_puncs:
            if ts_idx < len(timestamps):
                ts = timestamps[ts_idx]
                if start_time is None:
                    start_time = ts[0]
                end_time = ts[1]
                ts_idx += 1
        
        # Split condition
        # Update: Split on commas and semi-colons/colons to prevent long lines
        if char in "，。？！、；：,.?!;:":
            if start_time is not None and end_time is not None:
                segments.append({
                    "start": start_time,
                    "end": end_time,
                    "text": current_text.strip()
                })
                current_text = ""
                start_time = None
                # Keep end_time for gap calculation? No, reset.
        
    # Add remaining
    if current_text.strip() and start_time is not None:
        segments.append({
            "start": start_time,
            "end": end_time if end_time else start_time + 1000,
            "text": current_text.strip()
        })
        
    # Write SRT
    with open(output_srt, 'w', encoding='utf-8') as f:
        for i, seg in enumerate(segments):
            f.write(f"{i+1}\n")
            f.write(f"{format_time(seg['start'])} --> {format_time(seg['end'])}\n")
            # Strip punctuation
            clean_text = seg['text'].translate(str.maketrans('', '', "，。？！、；：,.?!;:"))
            f.write(f"{clean_text}\n\n")
            
    print(f"SRT generated at {output_srt}")
    
    # Cleanup memory
    print("Cleaning up ASR model memory...")
    del model
    import gc
    import torch
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
