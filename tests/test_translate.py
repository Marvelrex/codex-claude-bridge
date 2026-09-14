import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path

from bridge import translate as t


class FakePost:
    """Records calls and replays a queue of (status, payload) responses."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, headers, body, timeout):
        self.calls.append({"url": url, "headers": headers, "body": body, "timeout": timeout})
        if not self.responses:
            raise AssertionError("unexpected extra call")
        return self.responses.pop(0)


def ok(text, detected="ZH"):
    return 200, {"translations": [{"detected_source_language": detected, "text": text}]}


class HelpersTest(unittest.TestCase):
    def test_endpoint_by_key_suffix(self):
        self.assertEqual(t.endpoint_for("abc:fx"), t.FREE_URL)
        self.assertEqual(t.endpoint_for("abc"), t.PRO_URL)

    def test_contains_chinese(self):
        self.assertTrue(t.contains_chinese("hello 世界"))
        self.assertFalse(t.contains_chinese("hello world"))
        self.assertFalse(t.contains_chinese("，。！"))  # punctuation alone does not count


class TranslateTest(unittest.TestCase):
    def test_request_shape_and_result(self):
        post = FakePost(ok("Hello world"))
        out = t.translate("你好世界", "k:fx", post=post)
        self.assertEqual(out, "Hello world")
        call = post.calls[0]
        self.assertEqual(call["url"], t.FREE_URL)
        self.assertEqual(call["headers"]["Authorization"], "DeepL-Auth-Key k:fx")
        self.assertEqual(call["headers"]["Content-Type"], "application/json")
        self.assertEqual(call["body"]["text"], ["你好世界"])
        self.assertEqual(call["body"]["target_lang"], "EN-US")
        self.assertEqual(call["body"]["source_lang"], "ZH")
        self.assertTrue(call["body"]["preserve_formatting"])

    def test_auto_source_omits_source_lang_and_optional_fields(self):
        post = FakePost(ok("x"))
        t.translate("嗨", "k", source="auto", target="DE", formality="more", context="greeting", post=post)
        body = post.calls[0]["body"]
        self.assertNotIn("source_lang", body)
        self.assertEqual(body["target_lang"], "DE")
        self.assertEqual(body["formality"], "more")
        self.assertEqual(body["context"], "greeting")
        self.assertEqual(post.calls[0]["url"], t.PRO_URL)

    def test_retries_on_429_then_succeeds(self):
        post = FakePost((429, {"message": "slow down"}), ok("done"))
        sleeps = []
        out = t.translate("嗨", "k", post=post, sleep=sleeps.append)
        self.assertEqual(out, "done")
        self.assertEqual(len(post.calls), 2)
        self.assertEqual(len(sleeps), 1)

    def test_gives_up_after_retries(self):
        post = FakePost((500, "boom"), (529, "boom"), (500, "boom"))
        with self.assertRaises(t.DeepLError) as cm:
            t.translate("嗨", "k", post=post, sleep=lambda s: None, retries=2)
        self.assertEqual(cm.exception.status, 500)
        self.assertEqual(len(post.calls), 3)

    def test_403_and_456_do_not_retry(self):
        for status in (403, 456):
            post = FakePost((status, {"message": "nope"}))
            with self.assertRaises(t.DeepLError) as cm:
                t.translate("嗨", "k", post=post, sleep=lambda s: None)
            self.assertEqual(cm.exception.status, status)
            self.assertIn("nope", str(cm.exception))
            self.assertEqual(len(post.calls), 1)

    def test_network_error_wrapped(self):
        def post(url, headers, body, timeout):
            raise OSError("connection refused")
        with self.assertRaises(t.DeepLError) as cm:
            t.translate("嗨", "k", post=post)
        self.assertEqual(cm.exception.status, 0)


def run_main(argv, stdin_text=None, env_key="k:fx", post=None):
    out, err = io.StringIO(), io.StringIO()
    old_key = os.environ.get("DEEPL_AUTH_KEY")
    if env_key is None:
        os.environ.pop("DEEPL_AUTH_KEY", None)
    else:
        os.environ["DEEPL_AUTH_KEY"] = env_key
    stdin = io.StringIO(stdin_text if stdin_text is not None else "")
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = t.main(argv, stdin=stdin, post=post or FakePost(ok("translated")))
    finally:
        if old_key is None:
            os.environ.pop("DEEPL_AUTH_KEY", None)
        else:
            os.environ["DEEPL_AUTH_KEY"] = old_key
    return code, out.getvalue(), err.getvalue()


class MainTest(unittest.TestCase):
    def test_positional_text(self):
        code, out, err = run_main(["你好"])
        self.assertEqual((code, out.strip(), err), (0, "translated", ""))

    def test_stdin(self):
        code, out, _ = run_main([], stdin_text="你好\n")
        self.assertEqual((code, out.strip()), (0, "translated"))

    def test_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "in.md"
            p.write_text("中文内容", "utf-8")
            code, out, _ = run_main(["-f", str(p)])
            self.assertEqual((code, out.strip()), (0, "translated"))

    def test_passthrough_without_chinese_makes_no_call(self):
        post = FakePost()
        code, out, err = run_main(["already english"], post=post)
        self.assertEqual((code, out.strip()), (0, "already english"))
        self.assertEqual(post.calls, [])

    def test_force_translates_anyway(self):
        post = FakePost(ok("forced"))
        code, out, _ = run_main(["--force", "already english"], post=post)
        self.assertEqual((code, out.strip()), (0, "forced"))
        self.assertEqual(len(post.calls), 1)

    def test_missing_key_exit_2(self):
        code, out, err = run_main(["你好"], env_key=None)
        self.assertEqual(code, 2)
        self.assertIn("DEEPL_AUTH_KEY", err)
        self.assertEqual(out, "")

    def test_key_flag_overrides_env(self):
        post = FakePost(ok("x"))
        run_main(["--key", "flagkey", "你好"], post=post)
        self.assertEqual(post.calls[0]["headers"]["Authorization"], "DeepL-Auth-Key flagkey")
        self.assertEqual(post.calls[0]["url"], t.PRO_URL)

    def test_quota_exit_3(self):
        code, out, err = run_main(["你好"], post=FakePost((456, {"message": "Quota exceeded"})))
        self.assertEqual(code, 3)
        self.assertIn("Quota exceeded", err)

    def test_network_exit_4(self):
        def post(url, headers, body, timeout):
            raise OSError("down")
        code, out, err = run_main(["你好"], post=post)
        self.assertEqual(code, 4)

    def test_other_http_exit_5(self):
        code, out, err = run_main(["你好"], post=FakePost((400, {"message": "bad target_lang"})))
        self.assertEqual(code, 5)
        self.assertIn("bad target_lang", err)

    def test_empty_input_exit_1(self):
        code, out, err = run_main([], stdin_text="   ")
        self.assertEqual(code, 1)
