import unittest
from unittest.mock import MagicMock, patch
from src.processors.matcher import Matcher
from src.models import FolderWeight

class TestMatcher(unittest.TestCase):
    def setUp(self):
        self.matcher = Matcher("dummy_assets")

    @patch("src.processors.matcher.os.listdir")
    @patch("src.processors.matcher.os.path.exists")
    def test_weighted_route(self, mock_exists, mock_listdir):
        weights = [
            FolderWeight(folder="tech", weight=100),
            FolderWeight(folder="nature", weight=0)
        ]
        # Should always pick tech
        result = self.matcher.weighted_route(weights)
        self.assertTrue(result.endswith("tech"))

    @patch("src.processors.matcher.get_video_files")
    def test_pick_video(self, mock_get_files):
        mock_get_files.return_value = ["a.mp4", "b.mp4"]
        result = self.matcher.pick_video("some_folder")
        self.assertIn(result, ["a.mp4", "b.mp4"])
        
    # More tests can be added for slice logic with mocked VideoFileClip

if __name__ == '__main__':
    unittest.main()
