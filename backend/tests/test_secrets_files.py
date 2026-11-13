"""Secret-file rules. Local temporary files only; no services."""

import os
import tempfile
import unittest

from app.guard.errors import SecretFileError
from app.secrets_files import read_from_environ, read_secret_file, secret_roots

SENTINEL = "s3cr3t_SENTINEL_value_do_not_print"


class SecretFiles(unittest.TestCase):
    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp())
        self.roots = (self.root,)

    def tearDown(self):
        for dirpath, dirnames, filenames in os.walk(self.root, topdown=False):
            for name in filenames + dirnames:
                path = os.path.join(dirpath, name)
                try:
                    os.chmod(path, 0o700, follow_symlinks=False)
                except (NotImplementedError, OSError):
                    pass
                if os.path.isdir(path) and not os.path.islink(path):
                    os.rmdir(path)
                else:
                    os.unlink(path)
        os.rmdir(self.root)

    def write(self, name, content=SENTINEL + "\n", mode=0o600, raw=None):
        path = os.path.join(self.root, name)
        with open(path, "wb") as handle:
            handle.write(raw if raw is not None else content.encode())
        os.chmod(path, mode)
        return path

    def refused(self, code, path, **kwargs):
        with self.assertRaises(SecretFileError) as caught:
            read_secret_file(path, variable="NEXTUP_DB_PASSWORD_FILE", roots=self.roots, **kwargs)
        self.assertEqual(caught.exception.code, code)
        text = str(caught.exception) + repr(caught.exception)
        self.assertNotIn(SENTINEL, text)
        self.assertNotIn(self.root, text)
        self.assertIn("NEXTUP_DB_PASSWORD_FILE", str(caught.exception))
        return caught.exception

    def test_valid_files_and_newline_handling(self):
        for mode in (0o600, 0o400, 0o440, 0o640):
            with self.subTest(mode=oct(mode)):
                path = self.write(f"ok-{mode:o}", mode=mode)
                self.assertEqual(
                    read_secret_file(path, variable="X_FILE", roots=self.roots), SENTINEL
                )
        crlf = self.write("crlf", SENTINEL + "\r\n")
        self.assertEqual(read_secret_file(crlf, variable="X_FILE", roots=self.roots), SENTINEL)
        bare = self.write("bare", SENTINEL)
        self.assertEqual(read_secret_file(bare, variable="X_FILE", roots=self.roots), SENTINEL)

    def test_permissions_too_broad(self):
        for mode in (0o644, 0o604, 0o620, 0o602, 0o660, 0o601, 0o666):
            with self.subTest(mode=oct(mode)):
                self.refused("NXG-S03", self.write(f"broad-{mode:o}", mode=mode))

    def test_unexpected_owner(self):
        path = self.write("owned")
        self.refused("NXG-S07", path, allowed_owners=(os.geteuid() + 12345,))

    def test_symlinks_are_rejected(self):
        target = self.write("target")
        link = os.path.join(self.root, "link")
        os.symlink(target, link)
        self.refused("NXG-S02", link)
        os.mkdir(os.path.join(self.root, "real"))
        real_file = os.path.join(self.root, "real", "secret")
        with open(real_file, "w") as handle:
            handle.write(SENTINEL)
        os.chmod(real_file, 0o600)
        os.symlink(os.path.join(self.root, "real"), os.path.join(self.root, "dirlink"))
        self.refused("NXG-S02", os.path.join(self.root, "dirlink", "secret"))

    def test_unexpected_types_and_locations(self):
        directory = os.path.join(self.root, "a-directory")
        os.mkdir(directory)
        self.refused("NXG-S01", directory)
        fifo = os.path.join(self.root, "fifo")
        os.mkfifo(fifo, 0o600)
        self.refused("NXG-S01", fifo)
        self.refused("NXG-S01", os.path.join(self.root, "missing"))
        self.refused("NXG-S01", "relative/secret")
        outside = tempfile.NamedTemporaryFile(delete=False)
        try:
            os.chmod(outside.name, 0o600)
            self.refused("NXG-S02", os.path.realpath(outside.name))
        finally:
            os.unlink(outside.name)
        self.refused("NXG-S02", os.path.join(self.root, "..", "escape"))

    @unittest.skipIf(os.geteuid() == 0, "root can read mode-000 files")
    def test_unreadable(self):
        self.refused("NXG-S05", self.write("locked", mode=0o000))

    def test_content_bounds(self):
        cases = {
            "empty": b"",
            "only-newline": b"\n",
            "too-large": b"a" * 4097,
            "nul": b"abc\x00def",
            "multiline": b"line-one\nline-two\n",
            "carriage": b"abc\rdef",
            "not-utf8": b"\xff\xfe\xfa",
        }
        for name, raw in cases.items():
            with self.subTest(name):
                self.refused("NXG-S04", self.write(name, raw=raw))
        self.assertEqual(
            read_secret_file(
                self.write("exact", raw=b"a" * 4096), variable="X_FILE", roots=self.roots
            ),
            "a" * 4096,
        )

    def test_inline_and_file_conflict(self):
        path = self.write("both")
        environ = {"NEXTUP_X": SENTINEL, "NEXTUP_X_FILE": path, "NEXTUP_SECRETS_DIR": self.root}
        with self.assertRaises(SecretFileError) as caught:
            read_from_environ(environ, "NEXTUP_X")
        self.assertEqual(caught.exception.code, "NXG-C04")
        self.assertNotIn(SENTINEL, str(caught.exception))

    def test_file_source_and_roots(self):
        path = self.write("from-env")
        environ = {"NEXTUP_X_FILE": path, "NEXTUP_SECRETS_DIR": self.root}
        self.assertEqual(read_from_environ(environ, "NEXTUP_X"), SENTINEL)
        self.assertIsNone(read_from_environ({}, "NEXTUP_X"))
        self.assertEqual(secret_roots({}), ("/run/secrets",))
        with self.assertRaises(SecretFileError) as caught:
            secret_roots({"NEXTUP_SECRETS_DIR": "relative/dir"})
        self.assertEqual(caught.exception.code, "NXG-S02")
        # Without the operator directory the same file is outside the allowed roots.
        with self.assertRaises(SecretFileError) as caught:
            read_from_environ({"NEXTUP_X_FILE": path}, "NEXTUP_X")
        self.assertEqual(caught.exception.code, "NXG-S02")


if __name__ == "__main__":
    unittest.main()
