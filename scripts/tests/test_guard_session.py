"""guard_session.plan_apply against a real subprocess that behaves like
``python -m app.guard plan-apply``. No Docker, no database, no network."""

import sys
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import guard_session

FAKE_GUARD = textwrap.dedent(
    """
    import sys, time
    mode = sys.argv[1]
    def line(text):
        print("nextup-guard: " + text, flush=True)
    if mode == "sleep":
        time.sleep(30)
    kind = "NOOP" if mode == "noop" else "INIT"
    line(f"PLAN mode={kind} env=ci database=nextup_ci from=empty to=0029 steps=29")
    if mode == "noop":
        line("nothing to apply"); sys.exit(0)
    if mode == "refuse":
        print("nextup-guard: REFUSE NXG-I04 wrong role", file=sys.stderr, flush=True); sys.exit(3)
    line("confirmation=0123456789ab expires_in=600s single-use")
    line("awaiting confirmation")
    if mode == "exit-early":
        sys.exit(3)
    typed = sys.stdin.readline().strip()
    if typed != "0123456789ab":
        print("nextup-guard: REFUSE NXG-A11 not confirmed", file=sys.stderr, flush=True)
        sys.exit(3)
    line("APPLIED mode=INIT to=0029 env=ci")
    """
)


def command(mode):
    return [sys.executable, "-I", "-B", "-c", FAKE_GUARD, mode]


class PlanApplySession(unittest.TestCase):
    def test_confirmed_session_sends_only_the_code(self):
        seen = []

        def decide(lines, code):
            seen.append((list(lines), code))
            return code

        session = guard_session.plan_apply(command("init"), decide=decide, timeout=30)
        self.assertTrue(session.awaited and session.confirmed)
        self.assertEqual(session.returncode, 0)
        self.assertEqual(session.code, "0123456789ab")
        self.assertIn("nextup-guard: APPLIED mode=INIT to=0029 env=ci", session.lines)
        self.assertEqual(seen[0][0][-1], guard_session.AWAITING)

    def test_declining_closes_stdin_and_nothing_is_applied(self):
        session = guard_session.plan_apply(
            command("init"), decide=lambda lines, code: None, timeout=30
        )
        self.assertTrue(session.awaited)
        self.assertFalse(session.confirmed)
        self.assertEqual(session.returncode, 3)
        self.assertFalse(any("APPLIED" in line for line in session.lines))
        self.assertTrue(any("NXG-A11" in line for line in session.lines))

    def test_a_wrong_answer_is_refused_by_the_guard(self):
        session = guard_session.plan_apply(
            command("init"), decide=lambda lines, code: "ffffffffffff", timeout=30
        )
        self.assertEqual(session.returncode, 3)
        self.assertFalse(any("APPLIED" in line for line in session.lines))

    def test_nothing_to_apply_or_refusal_never_asks(self):
        for mode, code in (("noop", 0), ("refuse", 3)):
            with self.subTest(mode):
                asked = []
                session = guard_session.plan_apply(
                    command(mode),
                    decide=lambda lines, code, asked=asked: asked.append(1),
                    timeout=30,
                )
                self.assertFalse(session.awaited or session.confirmed or asked)
                self.assertEqual(session.returncode, code)

    def test_guard_exiting_before_the_answer_is_not_a_confirmation_error(self):
        session = guard_session.plan_apply(
            command("exit-early"), decide=lambda lines, code: code, timeout=30
        )
        self.assertEqual(session.returncode, 3)
        self.assertFalse(any("APPLIED" in line for line in session.lines))

    def test_timeout_kills_the_session(self):
        session = guard_session.plan_apply(
            command("sleep"), decide=lambda lines, code: code, timeout=1
        )
        self.assertTrue(session.timed_out)
        self.assertFalse(session.confirmed)
        self.assertNotEqual(session.returncode, 0)

    def test_an_interrupted_decision_kills_the_guard_and_applies_nothing(self):
        def interrupted(lines, code):
            raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            guard_session.plan_apply(command("init"), decide=interrupted, timeout=30)


if __name__ == "__main__":
    unittest.main()
