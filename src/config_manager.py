import json
import os
from typing import Dict, Any

CONFIG_FILE = "user_config.json"

DEFAULT_CONFIG = {
    "batch_count": 1,
    "res_option": "抖音 / Reels (1080x1920)",
    "custom_width": 1080,
    "custom_height": 1920,
    "prep_ratio": "抖音 (9:16)",
    "prep_custom_w": 1080,
    "prep_custom_h": 1920,
    "sub_font_name": "Noto Sans CJK SC",
    "sub_font_size": 9,
    "sub_outline": 1,
    "sub_bold": True,
    "sub_color": "#FFFFFF",
    "sub_shadow": 1,
    "sub_margin_v": 15,
    "bgm_selected": "无 (None)",
    "output_tag": "",
    # Folder weights will be stored as a list of dicts or a dict: {"folder_name": weight}
    "folder_weights": {},
    "ordered_folders": [] 
}

class ConfigManager:
    def __init__(self, config_file: str = CONFIG_FILE):
        self.config_file = config_file

    def load_config(self) -> Dict[str, Any]:
        """Load config from file, or return defaults if not found."""
        if not os.path.exists(self.config_file):
            return DEFAULT_CONFIG.copy()
        
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                saved_config = json.load(f)
                # Merge with default to ensure all keys exist (in case of updates)
                config = DEFAULT_CONFIG.copy()
                config.update(saved_config)
                return config
        except Exception as e:
            print(f"Error loading config: {e}")
            return DEFAULT_CONFIG.copy()

    def save_config(self, config_data: Dict[str, Any]):
        """Save the provided configuration dict to file."""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Error saving config: {e}")
            return False
