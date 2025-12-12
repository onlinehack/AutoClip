
import os
import sys
from src.models import FolderWeight
from src.processors.matcher import Matcher

def diagnose():
    assets_dir = os.path.join(os.getcwd(), "assets")
    print(f"Assets dir: {assets_dir}")
    
    matcher = Matcher(assets_dir)
    
    # Check folder weights
    folder_weights = [
        FolderWeight(folder="minecraft", weight=50),
        FolderWeight(folder="nature", weight=50)
    ]
    
    print("Testing weighted_route 100 times...")
    counts = {"minecraft": 0, "nature": 0}
    
    for _ in range(100):
        path = matcher.weighted_route(folder_weights)
        if "minecraft" in path:
            counts["minecraft"] += 1
        elif "nature" in path:
            counts["nature"] += 1
        else:
            print(f"Unexpected path: {path}")
            
    print(f"Results: {counts}")
    
    # Check pick_video
    print("\nTesting pick_video...")
    for folder_name in ["minecraft", "nature"]:
        folder_path = os.path.join(assets_dir, "video", folder_name)
        video_path = matcher.pick_video(folder_path)
        print(f"Picked video from {folder_name}: {video_path}")
        if not video_path or not os.path.exists(video_path):
            print("  ERROR: File does not exist!")

if __name__ == "__main__":
    diagnose()
