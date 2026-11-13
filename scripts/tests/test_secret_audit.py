"""Exact-value disclosure audit. Synthetic values; no engine, no network."""

import base64
import hashlib
import json
import os
import secrets
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import secret_audit

PROJECT = "nextup-ci-0123456789ab"
CONTAINER = "a" * 64


def fresh():
    audit = secret_audit.SecretAudit()
    value = secrets.token_urlsafe(32)
    audit.add("db_app_password", value)
    return audit, value


def found(audit):
    return {
        (f["secret"], f["variant"], f["source"]): f["count"] for f in audit.report()["findings"]
    }


class Detection(unittest.TestCase):
    def test_every_representation_is_detected(self):
        audit, value = fresh()
        raw = value.encode()
        cases = {
            "raw": raw,
            "base64@0": base64.b64encode(raw),
            "base64url@0": base64.urlsafe_b64encode(raw).rstrip(b"="),
            "hex": raw.hex().encode(),
            "HEX": raw.hex().upper().encode(),
            "utf16le": value.encode("utf-16-le"),
            "head16": b"truncated: " + raw[:16] + b"...",
            "tail16": b"..." + raw[-16:],
        }
        for offset, prefix in ((1, b"u:"), (2, b"ab:"), (0, b"abc")):
            cases[f"embedded base64@{(len(prefix)) % 3}/{offset}"] = base64.b64encode(
                prefix + raw + b"/tail"
            )
        for label, data in cases.items():
            with self.subTest(label):
                audit_case = secret_audit.SecretAudit()
                audit_case.add("db_app_password", value)
                audit_case.scan_bytes("src", b"before " + data + b" after")
                self.assertGreater(audit_case.disclosures(), 0, label)
                self.assertFalse(audit_case.result()["passed"])

    def test_percent_and_json_forms_of_values_that_need_escaping(self):
        audit = secret_audit.SecretAudit()
        value = 'pa ss/wo"rd+' + "x" * 20
        audit.add("db_admin_password", value)
        audit.scan_bytes(
            "url",
            ("https://h/?p=" + __import__("urllib.parse").parse.quote(value, safe="")).encode(),
        )
        audit.scan_bytes("json", json.dumps({"p": value}).encode())
        variants = {f["variant"] for f in audit.report()["findings"]}
        self.assertTrue({"percent", "json"} <= variants, variants)

    def test_token_and_its_components(self):
        audit = secret_audit.SecretAudit()
        token = "nxa1." + "P" * 120 + "." + "M" * 43
        audit.add("migration_token", token)
        audit.scan_bytes("mac-only", b"mac=" + b"M" * 43)
        self.assertIn(("migration_token", "part2", "mac-only"), found(audit))

    def test_the_token_format_is_found_without_knowing_the_value(self):
        audit = secret_audit.SecretAudit()
        token = "nxa1." + secrets.token_urlsafe(90) + "." + secrets.token_urlsafe(32)
        audit.scan_bytes("log", f"x token={token} y {token}".encode())
        audit.scan_bytes("masked", b"nextup-guard: token=<masked> nxa1.a.b nxa1.short.mac")
        self.assertEqual(found(audit), {("migration_token", "token-format", "log"): 2})
        self.assertNotIn(token, json.dumps(audit.report()))

    def test_the_token_format_across_read_chunks_is_counted_once(self):
        audit, _ = fresh()
        token = ("nxa1." + secrets.token_urlsafe(90) + "." + secrets.token_urlsafe(32)).encode()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "big.log"
            # one token straddles the chunk boundary, one sits wholly in the carried overlap
            path.write_bytes(
                b"x" * (secret_audit.CHUNK - 40)
                + token
                + b" " * 10
                + b"y" * (secret_audit.CHUNK - len(token) - 50)
                + token
            )
            audit.scan_file("evidence:big.log", path)
        self.assertEqual(found(audit)[("migration_token", "token-format", "evidence:big.log")], 2)

    def test_token_format_boundary_positions_are_counted_exactly_once(self):
        token = ("nxa1." + "P" * 120 + "." + "M" * 43).encode()
        cut_in_mac = secret_audit.CHUNK - (len(token) - 20)  # 23 MAC chars before the boundary
        cases = {
            "cut inside the MAC segment": b"x" * cut_in_mac + token + b" tail",
            "ends exactly at the chunk boundary": b"x" * (secret_audit.CHUNK - len(token))
            + token
            + b" tail",
            "ends exactly at end of file": b"x" * 100 + token,
            "ends at a boundary that is end of file": b"x" * (secret_audit.CHUNK - len(token))
            + token,
        }
        for label, data in cases.items():
            with self.subTest(label), tempfile.TemporaryDirectory() as directory:
                audit, _ = fresh()
                path = Path(directory) / "f.log"
                path.write_bytes(data)
                audit.scan_file("f", path)
                self.assertEqual(found(audit)[("migration_token", "token-format", "f")], 1)

    def test_no_false_positives_on_unrelated_material(self):
        audit, value = fresh()
        noise = " ".join(secrets.token_urlsafe(32) for _ in range(2000)).encode()
        audit.scan_bytes("noise", noise + base64.b64encode(noise))
        self.assertEqual(audit.disclosures(), 0)
        self.assertTrue(audit.result()["passed"])

    def test_short_values_and_unsafe_names_are_refused(self):
        audit = secret_audit.SecretAudit()
        with self.assertRaises(ValueError):
            audit.add("db_app_password", "short")
        with self.assertRaises(ValueError):
            audit.add("../evil", "x" * 40)

    def test_nothing_registered_is_never_a_pass(self):
        audit = secret_audit.SecretAudit()
        audit.scan_bytes("src", b"anything")
        self.assertFalse(audit.result()["complete"] or audit.result()["passed"])


class NoPlaintextEvidence(unittest.TestCase):
    def test_report_has_no_value_fragment_or_digest(self):
        audit, value = fresh()
        token = "nxa1." + secrets.token_urlsafe(90) + "." + secrets.token_urlsafe(32)
        audit.add("migration_token", token)
        audit.scan_bytes("log", f"{value} {token}".encode())
        text = json.dumps(audit.report()).encode()
        for secret in (value, token):
            raw = secret.encode()
            needles = list(secret_audit.variants(secret).values())
            needles += [
                hashlib.new(h, raw).hexdigest().encode()
                for h in ("md5", "sha1", "sha256", "sha512")
            ]
            needles += [base64.b64encode(hashlib.sha256(raw).digest()).rstrip(b"=")]
            for needle in needles:
                self.assertNotIn(needle, text)
        self.assertNotIn(value, repr(audit))

    def test_self_check_fails_closed_if_a_value_ever_reached_the_report(self):
        audit, value = fresh()
        with patch.object(
            secret_audit.SecretAudit, "result", return_value={"passed": True, "leak": value}
        ):
            report = audit.report()
        self.assertFalse(report["passed"])
        self.assertNotIn(value, json.dumps(report))

    def test_cleared_audit_drops_values_and_refuses_to_scan(self):
        audit, value = fresh()
        audit.clear()
        self.assertFalse(audit._needles)
        with self.assertRaises(RuntimeError):
            audit.scan_bytes("late", value.encode())
        self.assertFalse(audit.result()["complete"])


class Files(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.dir, ignore_errors=True))

    def test_tree_scan_reads_regular_files_and_never_follows_links(self):
        audit, value = fresh()
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(outside, ignore_errors=True))
        (outside / "secret.txt").write_text(value)
        (self.dir / "ok.log").write_text("clean")
        (self.dir / "sub").mkdir()
        (self.dir / "sub" / "leak.xml").write_text(f"<x>{value}</x>")
        (self.dir / "link.txt").symlink_to(outside / "secret.txt")
        (self.dir / "linkdir").symlink_to(outside)
        os.mkfifo(self.dir / "pipe")
        os.link(self.dir / "ok.log", outside / "hardlink")
        audit.scan_tree("evidence", self.dir)
        report = audit.report()
        self.assertEqual({f["source"] for f in report["findings"]}, {"evidence:sub/leak.xml"})
        kinds = {(a["source"], a["kind"]) for a in report["anomalies"]}
        self.assertIn(("evidence:link.txt", "not a regular file"), kinds)
        self.assertIn(("evidence:linkdir", "symlinked directory"), kinds)
        self.assertIn(("evidence:pipe", "not a regular file"), kinds)
        self.assertIn(("evidence:ok.log", "additional hard links"), kinds)
        self.assertFalse(report["passed"])

    def test_values_split_across_read_chunks_are_found_exactly_once(self):
        audit, value = fresh()
        path = self.dir / "big.log"
        with path.open("wb") as handle:
            handle.write(
                b"x" * (secret_audit.CHUNK - 10) + value.encode() + b"y" * 100 + value.encode()
            )
        audit.scan_file("evidence:big.log", path)
        self.assertEqual(found(audit)[("db_app_password", "raw", "evidence:big.log")], 2)

    def test_a_match_inside_the_carried_overlap_is_not_counted_twice(self):
        audit, value = fresh()
        raw = value.encode()
        path = self.dir / "edge.log"
        # First match ends exactly at the chunk boundary, so it lies wholly in the overlap
        # carried into the next read; the second match is inside the second chunk.
        with path.open("wb") as handle:
            handle.write(b"x" * (secret_audit.CHUNK - len(raw)) + raw + b"y" * 500 + raw)
        audit.scan_file("evidence:edge.log", path)
        self.assertEqual(found(audit)[("db_app_password", "raw", "evidence:edge.log")], 2)

    def test_rescanning_a_source_does_not_double_count(self):
        audit, value = fresh()
        (self.dir / "a.log").write_text(value)
        audit.scan_tree("evidence", self.dir)
        audit.scan_tree("evidence", self.dir)
        self.assertEqual(found(audit)[("db_app_password", "raw", "evidence:a.log")], 1)

    def test_root_that_is_a_symlink_is_an_anomaly(self):
        audit, _ = fresh()
        link = self.dir / "root"
        link.symlink_to(self.dir)
        audit.scan_tree("evidence", link)
        self.assertEqual(
            audit.report()["anomalies"],
            [{"source": "evidence", "kind": "root is not a real directory"}],
        )


class Engine(unittest.TestCase):
    def inspect_item(self, project=PROJECT, running=True, **config):
        return {
            "Id": CONTAINER,
            "Name": f"/{PROJECT}-worker-1",
            "Config": {"Labels": {"com.docker.compose.project": project}, **config},
            "State": {"Running": running},
        }

    def docker(self, items, environ=b"", calls=None):
        def run(args):
            if calls is not None:
                calls.append(list(args))
            if args[0] == "ps":
                return 0, "\n".join(i["Id"] for i in items).encode()
            if args[0] == "inspect":
                return 0, json.dumps(items).encode()
            return 0, environ

        return run

    def test_allowlist(self):
        ok = [
            ["ps", "-aq", "--no-trunc", "--filter", f"label=com.docker.compose.project={PROJECT}"],
            ["inspect", CONTAINER],
            ["exec", CONTAINER, "cat", "/proc/1/environ"],
            ["exec", CONTAINER, "stat", "-c", "%u:%g", "/proc/1"],
            ["exec", "--user", "999:999", CONTAINER, "cat", "/proc/1/environ"],
            ["exec", "--user", "1000:0", CONTAINER, "cat", "/proc/1/environ"],
        ]
        bad = [
            ["ps", "-aq"],
            ["ps", "-aq", "--no-trunc", "--filter", "label=com.docker.compose.project=x"],
            ["inspect", "name"],
            ["inspect"],
            ["exec", CONTAINER, "env"],
            ["logs", CONTAINER],
            ["rm", CONTAINER],
            ["exec", CONTAINER, "cat", "/proc/1/environ", "x"],
            ["image", "rm", "x"],
            # privilege-dropping fallback: exact shapes only, numeric non-root owner only
            ["exec", "--user", "0:0", CONTAINER, "cat", "/proc/1/environ"],
            ["exec", "--user", "root", CONTAINER, "cat", "/proc/1/environ"],
            ["exec", "--user", "999", CONTAINER, "cat", "/proc/1/environ"],
            ["exec", "--user", "999:999", CONTAINER, "cat", "/proc/2/environ"],
            ["exec", "--user", "999:999", CONTAINER, "cat", "/proc/1/environ", "x"],
            ["exec", "--user", "999:999", "name", "cat", "/proc/1/environ"],
            ["exec", "--user", "999:999;id", CONTAINER, "cat", "/proc/1/environ"],
            ["exec", "--privileged", "999:999", CONTAINER, "cat", "/proc/1/environ"],
            ["exec", "--privileged", CONTAINER, "cat", "/proc/1/environ"],
            ["exec", CONTAINER, "stat", "-c", "%u:%g", "/proc/2"],
            ["exec", CONTAINER, "stat", "-c", "%n", "/proc/1"],
            ["exec", CONTAINER, "stat", "-c", "%u:%g", "/proc/1", "/etc/shadow"],
            ["exec", "name", "stat", "-c", "%u:%g", "/proc/1"],
        ]
        for args in ok:
            self.assertTrue(secret_audit.allowed_engine_command(PROJECT, args), args)
        for args in bad:
            self.assertFalse(secret_audit.allowed_engine_command(PROJECT, args), args)

    def test_metadata_logs_and_environment_are_scanned(self):
        audit, value = fresh()
        calls = []
        items = [
            self.inspect_item(
                Env=["NEXTUP_DB_PASSWORD_FILE=/run/secrets/db_app_password"], Cmd=["celery", value]
            )
        ]
        secret_audit.collect_engine(
            audit,
            PROJECT,
            self.docker(items, f"A={value}\0".encode(), calls),
            lambda: f"worker-1 | {value}",
        )
        sources = {f["source"] for f in audit.report()["findings"]}
        self.assertEqual(
            sources,
            {
                f"engine:inspect:{PROJECT}-worker-1",
                "engine:compose-logs",
                f"engine:environ:{PROJECT}-worker-1",
            },
        )
        self.assertTrue(all(secret_audit.allowed_engine_command(PROJECT, c) for c in calls))

    def dropping(self, items, value, calls, owner=(0, b"999:999\n"), as_owner=None):
        """A service that dropped privileges: the default read is denied; the owner query and
        the read as that owner answer as given."""
        as_owner = (0, f"A={value}\0".encode()) if as_owner is None else as_owner
        base = self.docker(items)

        def run(args):
            calls.append(list(args))
            if args[0] != "exec":
                return base(args)
            if args[1] == "--user":
                return as_owner
            if args[2] == "stat":
                return owner
            return 1, b""  # cat: /proc/1/environ: Permission denied

        return run

    def test_privilege_dropping_service_is_read_as_its_own_user(self):
        """Run 3: postgres and redis run PID 1 as another uid, and root without CAP_SYS_PTRACE
        cannot read its environment. The audit must still scan it, as that user."""
        audit, value = fresh()
        calls = []
        secret_audit.collect_engine(
            audit, PROJECT, self.dropping([self.inspect_item()], value, calls), lambda: ""
        )
        report = audit.report()
        self.assertEqual(report["failed_sources"], {})
        self.assertTrue(report["complete"])
        self.assertEqual(
            {f["source"] for f in report["findings"]}, {f"engine:environ:{PROJECT}-worker-1"}
        )
        self.assertEqual(
            calls[-3:],
            [
                ["exec", CONTAINER, "cat", "/proc/1/environ"],
                ["exec", CONTAINER, "stat", "-c", "%u:%g", "/proc/1"],
                ["exec", "--user", "999:999", CONTAINER, "cat", "/proc/1/environ"],
            ],
        )
        self.assertTrue(all(secret_audit.allowed_engine_command(PROJECT, c) for c in calls))

    def test_a_readable_environment_needs_no_fallback(self):
        audit, value = fresh()
        calls = []
        secret_audit.collect_engine(
            audit,
            PROJECT,
            self.docker([self.inspect_item()], f"A={value}\0".encode(), calls),
            lambda: "",
        )
        self.assertEqual(
            [c for c in calls if c[0] == "exec"], [["exec", CONTAINER, "cat", "/proc/1/environ"]]
        )

    def test_privilege_dropping_fallback_fails_closed(self):
        cases = {
            "owner query fails": dict(owner=(1, b"")),
            "owner is root": dict(owner=(0, b"0:0\n")),
            "owner is a name": dict(owner=(0, b"postgres:postgres\n")),
            "owner output is hostile": dict(owner=(0, b"999:999 --privileged\n")),
            "owner output is empty": dict(owner=(0, b"")),
            "read as owner fails": dict(as_owner=(1, b"")),
        }
        for label, behaviour in cases.items():
            with self.subTest(label):
                audit, value = fresh()
                calls = []
                secret_audit.collect_engine(
                    audit,
                    PROJECT,
                    self.dropping([self.inspect_item()], value, calls, **behaviour),
                    lambda: "",
                )
                report = audit.report()
                self.assertIn(f"engine:environ:{PROJECT}-worker-1", report["failed_sources"])
                self.assertFalse(report["complete"])
                self.assertFalse(report["passed"])
                self.assertTrue(all(secret_audit.allowed_engine_command(PROJECT, c) for c in calls))
                if "owner" in behaviour:  # nothing is executed as an unverified user
                    self.assertFalse([c for c in calls if c[:2] == ["exec", "--user"]])

    def test_foreign_or_malformed_engine_output_fails_closed(self):
        audit, value = fresh()
        secret_audit.collect_engine(
            audit,
            PROJECT,
            self.docker([self.inspect_item(project="private")], value.encode()),
            lambda: "",
        )
        self.assertEqual(audit.disclosures(), 0)
        self.assertFalse(audit.result()["passed"])
        audit2, _ = fresh()
        secret_audit.collect_engine(audit2, PROJECT, lambda args: (0, b"not-an-id\n"), lambda: "")
        self.assertFalse(audit2.result()["complete"])
        audit3, _ = fresh()
        secret_audit.collect_engine(audit3, PROJECT, lambda args: (1, b""), lambda: "")
        self.assertIn("engine:ps", audit3.report()["failed_sources"])

    def test_a_docker_callable_cannot_be_asked_for_anything_else(self):
        audit, _ = fresh()
        with self.assertRaises(PermissionError):
            secret_audit.collect_engine(
                audit, "nextup-ci-; rm -rf /", lambda a: (0, b""), lambda: ""
            )


if __name__ == "__main__":
    unittest.main()
