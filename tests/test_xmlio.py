import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "examples"))

import make_sample  # noqa: E402
from sms_filter import xmlio  # noqa: E402


class RoundTripTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.src = os.path.join(self.dir, "backup.xml")
        make_sample.main(self.src)
        self.text, self.msgs = xmlio.read_backup(self.src)

    def write(self, remove):
        out = os.path.join(self.dir, "cleaned.xml")
        with open(out, "w", encoding="utf-8", newline="") as f:
            f.write(xmlio.remove_messages(self.text, self.msgs, remove))
        return out

    def test_reads_all_entries_including_mms_and_emoji(self):
        self.assertEqual(len(self.msgs), len(make_sample.CONVO))
        kinds = {m.kind for m in self.msgs}
        self.assertEqual(kinds, {"sms", "mms"})
        self.assertIn("\U0001F634", self.msgs[1].text)          # surrogate refs decoded
        self.assertIn("Pizza > everything", self.msgs[14].text)  # '>' inside an attribute

    def test_removing_nothing_is_byte_identical(self):
        out = self.write(set())
        with open(out, encoding="utf-8", newline="") as f:
            self.assertEqual(f.read(), self.text)

    def test_removal_keeps_everything_else_identical(self):
        remove = {2, 3, 17}  # includes the MMS entry
        out = self.write(remove)
        self.assertEqual(xmlio.verify(self.text, self.msgs, out, remove), [])
        with open(out, encoding="utf-8", newline="") as f:
            cleaned = f.read()
        self.assertIn(f'count="{len(self.msgs) - 3}"', cleaned)
        self.assertNotIn("Civic", cleaned)
        self.assertIn("&#55357;&#56884;", cleaned)  # emoji left in the app's own encoding

    def test_verify_detects_tampering(self):
        out = self.write({2})
        with open(out, encoding="utf-8") as f:
            data = f.read().replace("Pizza?", "Tacos?")
        with open(out, "w", encoding="utf-8", newline="") as f:
            f.write(data)
        self.assertTrue(xmlio.verify(self.text, self.msgs, out, {2}))


if __name__ == "__main__":
    unittest.main()
