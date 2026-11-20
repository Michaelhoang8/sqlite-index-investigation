"""Verify the integrity of published screenshot and recording artifacts."""
from pathlib import Path
import hashlib,json,unittest
ROOT=Path(__file__).resolve().parents[1]
class MediaChecks(unittest.TestCase):
    def test_captured_media_integrity(self):
        manifest=json.loads((ROOT/'docs/recordings/captures.json').read_text())
        self.assertEqual(hashlib.sha256((ROOT/'docs/recordings/walkthrough.mp4').read_bytes()).hexdigest(),manifest['video_sha256'])
        hashes=[]
        for capture in manifest['captures']:
            digest=hashlib.sha256((ROOT/capture['path']).read_bytes()).hexdigest()
            self.assertEqual(digest,capture['sha256']);hashes.append(digest)
        self.assertEqual(len(hashes),len(set(hashes)))
