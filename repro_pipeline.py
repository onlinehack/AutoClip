
import os
import shutil
import src.processors.tts
from src.pipeline import AutoClipPipeline
from src.models import MixConfig, FolderWeight

# Mock TTS to avoid network calls and speed up test
def mock_run_tts_sync(text, voice, output_file):
    print(f"Mock TTS: {text} -> {output_file}")
    # Create a dummy MP3 (copy sample bgm if exists, or create empty file)
    # We need a valid audio file for MoviePy.
    # Let's generate a simple sine wave using moviepy if needed, 
    # but here let's assume assets/bgm/sample_bgm.mp3 exists from setup.
    bgm_path = "assets/bgm/sample_bgm.mp3"
    if os.path.exists(bgm_path):
        shutil.copy(bgm_path, output_file)
    else:
        # Create a tiny valid mp3? Or just fail if setup wasn't run.
        # Let's try to just write some bytes or use moviepy to make one?
        # Simpler: use the one from setup_assets.py
        pass

src.processors.tts.run_tts_sync = mock_run_tts_sync

def test_pipeline():
    assets_dir = os.path.join(os.getcwd(), "assets")
    output_dir = os.path.join(os.getcwd(), "output")
    
    print(f"Assets: {assets_dir}")
    print(f"Output: {output_dir}")
    
    pipeline = AutoClipPipeline(assets_dir, output_dir)
    
    # Config with 50/50 weights
    folder_weights = [
        FolderWeight(folder="minecraft", weight=50),
        FolderWeight(folder="nature", weight=50)
    ]
    
    config = MixConfig(
        text="Sentence 1.\nSentence 2.\nSentence 3.\nSentence 4.",
        voice="zh-CN-XiaoxiaoNeural",
        folder_weights=folder_weights,
        batch_count=1,
        width=1080,
        height=1920,
        bgm_file=None # No BGM mixing to keep it simple
    )
    
    print("Running pipeline...")
    results = pipeline.run(config)
    print("Done.")
    print("Files:", results)

if __name__ == "__main__":
    test_pipeline()
