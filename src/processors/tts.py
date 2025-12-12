import edge_tts
import asyncio
import os
import random
import time

async def generate_tts(text: str, voice: str, output_file: str) -> None:
    """
    Generate TTS audio file using edge-tts with retry logic.
    """
    # Ensure directory exists
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    
    max_retries = 3
    last_error = None
    
    for attempt in range(max_retries):
        try:
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(output_file)
            return
        except Exception as e:
            last_error = e
            print(f"TTS Connection Warning: Attempt {attempt+1}/{max_retries} failed for text '{text[:10]}...'. Retrying...")
            await asyncio.sleep(1 + random.random())  # Random delay 1-2s
            
    # If we get here, all retries failed
    raise RuntimeError(f"TTS failed after {max_retries} attempts. Last error: {str(last_error)}. Please checks your network connection (Edge TTS requires access to Microsoft servers).")

def run_tts_sync(text: str, voice: str, output_file: str) -> None:
    """
    Synchronous wrapper for TTS generation.
    """
    try:
        asyncio.run(generate_tts(text, voice, output_file))
    except Exception as e:
        raise e

