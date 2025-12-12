import os
import numpy as np
from moviepy.editor import ColorClip, AudioFileClip, AudioClip

def create_dirs():
    dirs = [
        "assets",
        "assets/bgm",
        "assets/video",
        "assets/video/minecraft",
        "assets/video/nature",
        "output"
    ]
    for d in dirs:
        os.makedirs(d, exist_ok=True)
        print(f"Created directory: {d}")

def create_dummy_videos():
    # Create some dummy videos
    # 1. Minecraft (Green-ish)
    print("Generating sample videos for 'minecraft'...")
    for i in range(3):
        # 5 seconds, 1080x1920 (Vertical)
        clip = ColorClip(size=(1080, 1920), color=(50, 205 + i*10, 50), duration=5)
        clip.fps = 24
        filename = f"assets/video/minecraft/sample_mc_{i}.mp4"
        clip.write_videofile(filename, codec="libx264", audio=False, logger=None)
        print(f"  Generated {filename}")

    # 2. Nature (Blue-ish)
    print("Generating sample videos for 'nature'...")
    for i in range(3):
        # 5 seconds, 1080x1920 (Vertical)
        clip = ColorClip(size=(1080, 1920), color=(100, 100, 200 + i*10), duration=5)
        clip.fps = 24
        filename = f"assets/video/nature/sample_nature_{i}.mp4"
        clip.write_videofile(filename, codec="libx264", audio=False, logger=None)
        print(f"  Generated {filename}")

def create_dummy_bgm():
    print("Generating sample BGM...")
    # 10 seconds of silence/tone
    make_frame = lambda t: np.sin(2 * np.pi * 440 * t) # 440 Hz sine wave
    clip = AudioClip(make_frame, duration=10, fps=44100)
    filename = "assets/bgm/sample_bgm.mp3"
    clip.write_audiofile(filename, fps=44100, logger=None)
    print(f"  Generated {filename}")

if __name__ == "__main__":
    create_dirs()
    try:
        create_dummy_videos()
        create_dummy_bgm()
        print("Success! Asset files generated.")
    except Exception as e:
        print(f"Error generating assets: {e}")
        # If moviepy fails (e.g. ffmpeg missing), we still have the dirs.
