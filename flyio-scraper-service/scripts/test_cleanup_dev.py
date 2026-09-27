import json
import os
import unittest
from unittest.mock import patch, Mock
import cleanup_dev as cleanup


class CleanupTests(unittest.TestCase):
    def test_only_older_scoped_release_removed_without_volumes(self):
        def container(id, created, image, service="admin-dev"):
            return {"Id": id, "Name": "/"+id, "Created": created, "Image": image,
                    "Config": {"Labels": {"flyio.service": service}}, "State": {"Running": True}}
        records = {"candidate": container("active", "2026-02", "image-active"),
                   "active": container("active", "2026-02", "image-active"),
                   "old": container("old", "2026-01", "image-old"),
                   "new": container("new", "2026-03", "image-new"),
                   "other": container("other", "2026-01", "image-other", "llm-dev")}
        def docker(*args):
            if args[0] == "inspect": return json.dumps([records[args[1]]])
            if args[-1].startswith("label="): return "active\nold\nnew\nother"
            return ""
        with patch.dict(os.environ, {"CANDIDATE": "candidate", "CLEANUP_SERVICE": "admin-dev"}), \
             patch.object(cleanup, "docker", side_effect=docker), \
             patch.object(cleanup, "connect", return_value=(None, None, {"forward_host": "candidate", "forward_scheme": "http", "forward_port": 3000})), \
             patch.object(cleanup, "verify_public"), \
             patch.object(cleanup.subprocess, "run", return_value=Mock(returncode=0)) as run:
            cleanup.cleanup()
        self.assertEqual([c.args[0] for c in run.call_args_list], [
            ["docker", "stop", "--time", "30", "old"],
            ["docker", "rm", "old"], ["docker", "image", "rm", "image-old"]])


if __name__ == "__main__":
    unittest.main()
