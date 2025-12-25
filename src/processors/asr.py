import os
import math
from datetime import datetime
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
    import torch
    import os
    
    device = "cuda" if torch.cuda.is_available() else "cpu"
    
    # Xeon/Multi-core Optimization
    if device == "cpu":
        try:
            # Get core count (logical)
            num_cores = os.cpu_count() or 4
            # PyTorch often defaults to 1 or halves it on some systems. 
            # We explicitly maximize it for Xeon.
            # However, avoid excessive thread contention if cores > 32? 
            # Usually strict setting to core count is safe for a single heavy task.
            torch.set_num_threads(num_cores)
            # interop threads handle parallelism between independent ops. 
            # 2-4 is usually sufficient.
            torch.set_num_interop_threads(4) 
            
            print(f"[{datetime.now()}] [ASR] CPU Optimization: Configured PyTorch to use {num_cores} threads (Device: {device}).")
        except Exception as e:
            print(f"[{datetime.now()}] [ASR] CPU Optimization Warning: {e}")

    print(f"[{datetime.now()}] [ASR] Loading FunASR model using device: {device}...")

    try:
        model = AutoModel(
            model="paraformer-zh",
            vad_model="fsmn-vad",
            punc_model="ct-punc",
            log_level="ERROR",
            # device=device # AutoModel usually detects, but we can rely on default
        )
        print(f"[{datetime.now()}] [ASR] Model loaded.")
    except Exception as e:
        print(f"[{datetime.now()}] [ASR] Error loading FunASR model: {e}")
        raise e
    
    
    print(f"[{datetime.now()}] [ASR] Running inference (Batch Size: 60s)...")
    try:
        # Reduced batch_size_s from 300 to 60 to prevent long pauses/hangs on long files
        res = model.generate(input=audio_file, batch_size_s=60)
        print(f"[{datetime.now()}] [ASR] Inference completed. Processing results...")
    except Exception as e:
        print(f"[{datetime.now()}] [ASR] Error running inference: {e}")
        raise e
    
    if not res:
        print(f"[{datetime.now()}] [ASR] Warning: No result from ASR.")
        with open(output_srt, 'w', encoding='utf-8') as f:
            pass
        return

    # Use the first result
    entry = res[0]
    text = entry.get('text', '')
    timestamps = entry.get('timestamp', []) # List of [start, end] in ms

    print(f"[{datetime.now()}] [ASR] Text Length: {len(text)}, Timestamps: {len(timestamps)}")

    if not text or not timestamps:
         print("Warning: Empty text or timestamps.")
         with open(output_srt, 'w', encoding='utf-8') as f:
            pass
         return
    
    # Logic to split by punctuation
    segments = []
    
    current_text = ""
    start_time = None
    end_time = None
    
    ts_idx = 0
    
    # Process text loop
    start_process_time = datetime.now()
    
    for char in text:
        current_text += char
        
        # Check if this char has a timestamp (is it a normal char?)
        full_puncs = "，。？！、；：,.?!;:"
        
        if char not in full_puncs:
            if ts_idx < len(timestamps):
                ts = timestamps[ts_idx]
                if start_time is None:
                    start_time = ts[0]
                end_time = ts[1]
                ts_idx += 1
        
        # Split condition
        if char in "，。？！、；：,.?!;:":
            if start_time is not None and end_time is not None:
                segments.append({
                    "start": start_time,
                    "end": end_time,
                    "text": current_text.strip()
                })
                current_text = ""
                start_time = None
        
    # Add remaining
    if current_text.strip() and start_time is not None:
        segments.append({
            "start": start_time,
            "end": end_time if end_time else start_time + 1000,
            "text": current_text.strip()
        })
    
    print(f"[{datetime.now()}] [ASR] Post-processing took {datetime.now() - start_process_time}. Segments found: {len(segments)}")

    # Write SRT
    with open(output_srt, 'w', encoding='utf-8') as f:
        for i, seg in enumerate(segments):
            f.write(f"{i+1}\n")
            f.write(f"{format_time(seg['start'])} --> {format_time(seg['end'])}\n")
            # Strip punctuation
            clean_text = seg['text'].translate(str.maketrans('', '', "，。？！、；：,.?!;:"))
            f.write(f"{clean_text}\n\n")
            
    print(f"[{datetime.now()}] [ASR] SRT generated at {output_srt}")
    
    # Cleanup memory
    print(f"[{datetime.now()}] [ASR] Cleaning up ASR model memory...")
    del model
    import gc
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
