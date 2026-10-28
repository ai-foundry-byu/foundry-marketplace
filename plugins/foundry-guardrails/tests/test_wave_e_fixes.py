"""Regression tests for the wave-E live findings (E2-3a, E2-3b).

E2-3a: `env | grep -i '^AWS' | cut -d= -f1` prints names only, but was denied.
E2-3b: archive and compress round trips printed a dotenv file with no deny:
`gzip -dc env.gz`, `gzip -c .env | zcat`, `tar czf e.tgz .env && tar xzOf e.tgz`, and a
read-back of an archive made in an earlier command.
"""
import os
import unittest

from helpers import HookCase

import secret_guard as sg

S = "secret_guard.py"


class NamesOnlyAfterGrep(unittest.TestCase):
    def allow(self, cmd):
        self.assertIsNone(sg.evaluate_bash(cmd), f"expected allow: {cmd}")

    def deny(self, cmd):
        self.assertIsNotNone(sg.evaluate_bash(cmd), f"expected deny: {cmd}")

    def test_grep_then_cut_names_is_allowed(self):
        for cmd in ["env | grep -i '^AWS' | cut -d= -f1",
                    "printenv | grep AWS | cut -d= -f1 | sort",
                    "env | grep -i aws | cut -d= -f1 | wc -l",
                    "env | grep -E '^(AWS|GCP)_' | sed 's/=.*//'"]:
            self.allow(cmd)

    def test_value_printing_forms_stay_denied(self):
        for cmd in ["env | grep -i aws",
                    "env | grep AWS | cut -d= -f2",
                    "env | grep AWS | tee aws.txt | cut -d= -f1",
                    "env | grep AWS | cut -d= -f1-",
                    "printenv | grep AWS"]:
            self.deny(cmd)


class ArchiveRoundTripsSameCommand(unittest.TestCase):
    def allow(self, cmd):
        self.assertIsNone(sg.evaluate_bash(cmd), f"expected allow: {cmd}")

    def deny(self, cmd):
        self.assertIsNotNone(sg.evaluate_bash(cmd), f"expected deny: {cmd}")

    def test_decompress_to_screen_of_secret_named_archives(self):
        for cmd in ["gzip -dc .env.gz", "gzip -d -c .env.gz", "gunzip -c .env.gz",
                    "bzcat .env.bz2", "xzcat .env.xz", "zstdcat .env.zst", "bzip2 -dc .env.bz2",
                    "xz -dc .env.xz", "zstd -dc .env.zst"]:
            self.deny(cmd)

    def test_compress_a_secret_to_the_screen_or_a_pipe(self):
        for cmd in ["gzip -c .env", "gzip -c .env | zcat", "gzip -c .env | base64",
                    "bzip2 -c .env | bzcat", "tar czf - .env | tar xzOf -", "tar cf - .env"]:
            self.deny(cmd)

    def test_archive_made_then_read_back_in_one_command(self):
        for cmd in ["gzip -c .env > env.gz && zcat env.gz",
                    "gzip -c .env > env.gz && gzip -dc env.gz",
                    "tar czf e.tgz .env && tar xzOf e.tgz",
                    "tar -czf e.tgz .env; tar -xzOf e.tgz",
                    "zip e.zip .env && unzip -p e.zip",
                    "gzip -k -f .env && mv .env.gz env.gz && gzip -dc env.gz"]:
            self.deny(cmd)

    def test_ordinary_archives_are_fine(self):
        for cmd in ["gzip -c app.log | zcat", "zcat access.log.gz", "tar czf src.tgz src",
                    "tar czf src.tgz src && tar xzOf src.tgz", "gzip -k notes.txt",
                    "unzip -p release.zip README.md", "gzip -c .env > env.gz",
                    "tar czf backup.tgz .env"]:
            self.allow(cmd)


class ArchiveRoundTripsAcrossCommands(HookCase):
    def test_archive_made_earlier_then_read_back(self):
        # E2-3b live: gzip the .env in one command, read the archive back in a later one.
        self.assertAllowed(self.run_hook(S, self.bash("gzip -k -f .env && mv .env.gz env.gz",
                                                      cwd=self.tmp)))
        self.assertDenied(self.run_hook(S, self.bash("gzip -dc env.gz", cwd=self.tmp)),
                          "copy")
        self.assertAllowed(self.run_hook(S, self.bash("tar czf e.tgz .env", cwd=self.tmp)))
        self.assertDenied(self.run_hook(S, self.bash("tar xzOf e.tgz", cwd=self.tmp)), "copy")
        self.assertAllowed(self.run_hook(S, self.bash("cp .env /tmp/x.txt", cwd=self.tmp)))
        self.assertDenied(self.run_hook(S, self.bash("cat /tmp/x.txt", cwd=self.tmp)), "copy")

    def test_other_sessions_and_other_files_are_not_affected(self):
        self.assertAllowed(self.run_hook(S, self.bash("gzip -c .env > env.gz", cwd=self.tmp,
                                                      session="s1")))
        self.assertAllowed(self.run_hook(S, self.bash("gzip -dc env.gz", cwd=self.tmp,
                                                      session="s2")))
        self.assertAllowed(self.run_hook(S, self.bash("zcat other.gz", cwd=self.tmp,
                                                      session="s1")))

    def test_corrupt_state_fails_open(self):
        os.makedirs(self.state, exist_ok=True)
        with open(os.path.join(self.state, "secret-derived-s1"), "w") as fh:
            fh.write("{not json")
        self.assertAllowed(self.run_hook(S, self.bash("zcat other.gz", cwd=self.tmp)))


if __name__ == "__main__":
    unittest.main()


class NamesOnlyAfterGrepWithSourcedFiles(HookCase):
    """The grep-then-cut allowance must keep the sourced-file check: a multi-line value in a
    sourced .env prints its continuation lines whole through cut -f1."""

    def setUp(self):
        super().setUp()
        self.proj = os.path.realpath(os.path.join(self.tmp, "proj"))
        os.makedirs(os.path.join(self.proj, "sub"))
        with open(os.path.join(self.proj, ".env"), "w") as fh:
            fh.write("AWS_REGION=us-fake-1\nDEBUG=1\n")
        with open(os.path.join(self.proj, "sub", ".env"), "w") as fh:
            fh.write('AWS_PEM="-----BEGIN KEY-----\nAWSMIIEabcdefghijklmnop\n-----END KEY-----"\n')
        self.env = {k: v for k, v in self.env.items() if "\n" not in v}

    def sg(self, cmd):
        return self.run_hook(S, self.bash(cmd, cwd=self.proj))

    def test_multiline_sourced_values_still_deny(self):
        self.assertDenied(self.sg("source sub/.env && env | grep AWS | cut -d= -f1"))
        self.assertAllowed(self.sg("source .env && env | grep AWS | cut -d= -f1"))
