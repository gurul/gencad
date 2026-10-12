"""The test suite's temp-directory cleanup retries exactly one Windows error.

Pins ``RetryingTemporaryDirectory``: ``WinError 32`` (a scanner still holding a
file this process just read) is waited out through a bounded ladder, and every
other error -- including an unbeaten ladder -- propagates so a real leaked
handle still fails the test that leaked it.
"""

from __future__ import annotations

import unittest
from unittest import mock

from tests.python.support import tmp_root
from tests.python.support.tmp_root import RetryingTemporaryDirectory


def _sharing_violation() -> PermissionError:
    error = PermissionError(13, "The process cannot access the file because it is being used by another process")
    error.winerror = tmp_root.WINDOWS_SHARING_VIOLATION
    return error


class RetryingTemporaryDirectoryTests(unittest.TestCase):
    def _cleanup_with(self, failures: list[OSError]) -> tuple[int, list[float]]:
        """Run cleanup against a base cleanup that fails with ``failures`` in order, then succeeds."""
        attempts = 0
        original = tmp_root.tempfile.TemporaryDirectory.cleanup

        def flaky_cleanup(instance):
            nonlocal attempts
            attempts += 1
            if failures:
                raise failures.pop(0)
            original(instance)

        sleeps: list[float] = []
        tempdir = RetryingTemporaryDirectory(prefix="tmp-retrying-cleanup-")
        with (
            mock.patch.object(tmp_root.tempfile.TemporaryDirectory, "cleanup", flaky_cleanup),
            mock.patch("time.sleep", side_effect=sleeps.append),
        ):
            tempdir.cleanup()
        return attempts, sleeps

    def test_a_sharing_violation_is_retried_then_the_directory_goes(self) -> None:
        attempts, sleeps = self._cleanup_with([_sharing_violation(), _sharing_violation()])
        self.assertEqual(3, attempts)
        self.assertEqual(list(tmp_root.CLEANUP_RETRY_DELAYS_SECONDS[:2]), sleeps)

    def test_the_ladder_is_bounded_and_the_last_error_propagates(self) -> None:
        budget = len(tmp_root.CLEANUP_RETRY_DELAYS_SECONDS) + 1
        failures = [_sharing_violation() for _ in range(budget + 3)]
        with self.assertRaises(PermissionError) as raised:
            self._cleanup_with(failures)
        self.assertEqual(tmp_root.WINDOWS_SHARING_VIOLATION, raised.exception.winerror)
        # One attempt per delay plus the final unslept one; the extras were never tried.
        self.assertEqual(3, len(failures))

    def test_any_other_error_propagates_at_once(self) -> None:
        denied = PermissionError(13, "Access is denied")
        denied.winerror = 5
        with self.assertRaises(PermissionError) as raised:
            self._cleanup_with([denied])
        self.assertEqual(5, raised.exception.winerror)

    def test_off_windows_the_error_has_no_winerror_and_propagates(self) -> None:
        with self.assertRaises(PermissionError):
            self._cleanup_with([PermissionError(13, "no winerror attribute here")])

    def test_a_clean_cleanup_removes_the_directory(self) -> None:
        tempdir = RetryingTemporaryDirectory(prefix="tmp-retrying-cleanup-")
        path = tempdir.name
        tempdir.cleanup()
        import os

        self.assertFalse(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
