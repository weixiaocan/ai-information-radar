from __future__ import annotations

import unittest

from main import payload_exit_code


class MainExitCodeTest(unittest.TestCase):
    def test_blocked_payload_is_nonzero(self) -> None:
        self.assertEqual(3, payload_exit_code({"status": "blocked"}))

    def test_normal_payload_is_zero(self) -> None:
        self.assertEqual(0, payload_exit_code({"status": "ok"}))
        self.assertEqual(0, payload_exit_code([{"item": 1}]))


if __name__ == "__main__":
    unittest.main()
