#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
麦门树洞 · 本地档案模块测试

覆盖 scripts/profile.py 的三块逻辑：

  1. 档案读写（含旧版本字段补齐与损坏文件兜底）
  2. 价格解析与记账写入
  3. **时间维度的事实**（第 N 次 / 星期规律 / 价格变化）—— 本项目差异化所在

设计原则：

  - **零第三方依赖**，纯标准库 `unittest`，clone 下来就能跑
  - **全程使用临时档案**，绝不触碰 `user_data/profile.json`
  - 断言的是**「允许说 / 不允许说」的结论**，而不是话术字符串本身。
    话术会改，但"什么时候不能说"是红线。

运行：

    python tests/test_recall.py
    python tests/test_recall.py -v
"""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
PROFILE_PATH = ROOT / "scripts" / "profile.py"

# 加载被测模块（不会触发 __main__）
_spec = importlib.util.spec_from_file_location("wb_profile_mod", PROFILE_PATH)
profile = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(profile)          # type: ignore[union-attr]

MONDAY = datetime(2026, 10, 12, 20, 30)    # 2026-10-12 是周一


# ----------------------------------------------------------------------
# 辅助
# ----------------------------------------------------------------------

def _blank_profile() -> dict:
    return json.loads(json.dumps(profile.EMPTY_PROFILE))


def entry(time_str: str, prices=None, mood=None, paid=None) -> dict:
    e = {"time": time_str, "items": "", "saved": 0.0, "mood": mood}
    if prices:
        e["prices"] = prices
    if paid is not None:
        e["paid"] = paid
    return e


def monday(weeks_ago: int, hour: int = 20) -> str:
    return (MONDAY - timedelta(weeks=weeks_ago)).replace(hour=hour).strftime("%Y-%m-%d %H:%M")


def recall(history, journal=None, mood=None) -> str:
    """用临时档案执行 cmd_recall，返回其标准输出。"""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "profile.json"
        data = _blank_profile()
        data["ledger"]["history"] = history
        data["ledger"]["order_count"] = len(history)
        data["journal"] = journal or []
        with p.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        buf = io.StringIO()
        with redirect_stdout(buf):
            profile.cmd_recall(SimpleNamespace(path=p, mood=mood))
        return buf.getvalue()


# ----------------------------------------------------------------------
# 1. 价格解析
# ----------------------------------------------------------------------

class TestParsePrices(unittest.TestCase):

    def test_single(self):
        self.assertEqual(profile.parse_prices(["巨无霸=25.5"]), {"巨无霸": 25.5})

    def test_multiple(self):
        got = profile.parse_prices(["巨无霸=25.5", "新地=12"])
        self.assertEqual(got, {"巨无霸": 25.5, "新地": 12.0})

    def test_int_is_coerced_to_float(self):
        self.assertEqual(profile.parse_prices(["麦香鸡=17"]), {"麦香鸡": 17.0})

    def test_empty_input_is_empty_dict(self):
        self.assertEqual(profile.parse_prices(None), {})
        self.assertEqual(profile.parse_prices([]), {})

    def test_missing_equals_rejected(self):
        with self.assertRaises(ValueError):
            profile.parse_prices(["巨无霸25.5"])

    def test_empty_name_rejected(self):
        with self.assertRaises(ValueError):
            profile.parse_prices(["=25.5"])

    def test_non_numeric_amount_rejected(self):
        with self.assertRaises(ValueError):
            profile.parse_prices(["巨无霸=二十五"])

    def test_name_with_space_is_stripped(self):
        self.assertEqual(profile.parse_prices(["  巨无霸 =25.5"]), {"巨无霸": 25.5})


# ----------------------------------------------------------------------
# 2. 档案读写
# ----------------------------------------------------------------------

class TestProfileIO(unittest.TestCase):

    def test_load_missing_file_returns_empty_profile(self):
        with tempfile.TemporaryDirectory() as d:
            data = profile.load(Path(d) / "nope.json")
            self.assertEqual(data["ledger"]["order_count"], 0)
            self.assertEqual(data["journal"], [])

    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "profile.json"
            data = _blank_profile()
            data["constraints"]["allergies"] = ["花生"]
            profile.save(p, data)
            self.assertEqual(profile.load(p)["constraints"]["allergies"], ["花生"])

    def test_missing_fields_are_backfilled(self):
        """旧版本档案缺字段时应补齐，而不是 KeyError。"""
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "profile.json"
            p.write_text(json.dumps({"version": 1}), encoding="utf-8")
            data = profile.load(p)
            self.assertIn("constraints", data)
            self.assertIn("ledger", data)
            self.assertIn("journal", data)

    def test_corrupt_json_exits_cleanly(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "profile.json"
            p.write_text("{ this is not json", encoding="utf-8")
            with self.assertRaises(SystemExit):
                profile.load(p)

    def test_save_is_atomic(self):
        """写入后不应残留 .tmp 文件。"""
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "profile.json"
            profile.save(p, _blank_profile())
            leftovers = list(Path(d).glob("*.tmp"))
            self.assertEqual(leftovers, [])

    def test_weekday_cn(self):
        self.assertEqual(profile.weekday_cn(MONDAY), "周一")
        self.assertEqual(profile.weekday_cn(MONDAY + timedelta(days=3)), "周四")
        self.assertEqual(profile.weekday_cn(MONDAY + timedelta(days=6)), "周日")


# ----------------------------------------------------------------------
# 3. record 写入
# ----------------------------------------------------------------------

class TestRecord(unittest.TestCase):

    def test_record_persists_prices_and_paid(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "profile.json"
            args = SimpleNamespace(path=p, items="巨无霸,新地", saved=0.0,
                                   paid=37.5, price=["巨无霸=25.5", "新地=12"],
                                   mood="加班")
            with redirect_stdout(io.StringIO()):
                profile.cmd_record(args)
            hist = profile.load(p)["ledger"]["history"]
            self.assertEqual(len(hist), 1)
            self.assertEqual(hist[0]["prices"], {"巨无霸": 25.5, "新地": 12.0})
            self.assertEqual(hist[0]["paid"], 37.5)

    def test_record_without_price_has_no_prices_key(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "profile.json"
            args = SimpleNamespace(path=p, items="巨无霸", saved=5.0,
                                   paid=None, price=None, mood=None)
            with redirect_stdout(io.StringIO()):
                profile.cmd_record(args)
            hist = profile.load(p)["ledger"]["history"]
            self.assertNotIn("prices", hist[0])
            self.assertNotIn("paid", hist[0])

    def test_bad_price_format_exits_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "profile.json"
            args = SimpleNamespace(path=p, items="巨无霸", saved=0.0,
                                   paid=None, price=["巨无霸25.5"], mood=None)
            with self.assertRaises(SystemExit):
                profile.cmd_record(args)
            self.assertFalse(p.exists(), "格式错误时不应写入档案")

    def test_total_saved_accumulates(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "profile.json"
            for saved in (13.5, 5.0):
                args = SimpleNamespace(path=p, items="x", saved=saved,
                                       paid=None, price=None, mood=None)
                with redirect_stdout(io.StringIO()):
                    profile.cmd_record(args)
            self.assertAlmostEqual(profile.load(p)["ledger"]["total_saved"], 18.5)


# ----------------------------------------------------------------------
# 4. 时间维度 · 计数
# ----------------------------------------------------------------------

class TestRecallCounting(unittest.TestCase):

    def test_two_records_allow_nth_phrase(self):
        hist = [entry(monday(1), mood="加班"), entry(monday(0), mood="加班")]
        out = recall(hist, mood="加班")
        self.assertIn("已出现 2 次", out)
        self.assertNotIn("不可以用", out)

    def test_single_record_refuses_nth_phrase(self):
        out = recall([entry(monday(0), mood="加班")], mood="加班")
        self.assertIn("不可以用", out)

    def test_absent_mood_refuses_nth_phrase(self):
        out = recall([entry(monday(0), mood="加班")], mood="开心")
        self.assertIn("不可以用", out)

    def test_journal_entries_count_toward_nth(self):
        hist = [entry(monday(1), mood="加班")]
        journal = [{"time": monday(0), "text": "又加班", "mood": "加班"}]
        out = recall(hist, journal=journal, mood="加班")
        self.assertIn("已出现 2 次", out)


# ----------------------------------------------------------------------
# 5. 时间维度 · 星期规律（核心：不许把"同一天多次"说成"连着 N 个周X"）
# ----------------------------------------------------------------------

class TestRecallWeekday(unittest.TestCase):

    def test_consecutive_weeks_allowed(self):
        hist = [entry(monday(w), mood="加班") for w in (2, 1, 0)]
        out = recall(hist, mood="加班")
        self.assertIn("可以说「连着 3 个周一了」", out)

    def test_same_day_multiple_orders_must_refuse(self):
        """同一天点 3 次，绝不是「连着 3 个周一」。

        注意断言写法：拒单句是「不可以说『连着 N 个周一』」，它**本身
        就含有** `可以说「连着` 这个子串，所以只能匹配肯定分支独有的
        标记「个连续周」。断言踩这个坑，正说明这条红线有多容易被绕过。
        """
        hist = [entry(monday(0, hour=h), mood="加班") for h in (18, 19, 20)]
        out = recall(hist, mood="加班")
        self.assertIn("只出现过 1 天", out)
        self.assertNotIn("个连续周", out)

    def test_gap_of_two_weeks_is_not_consecutive(self):
        hist = [entry(monday(0), mood="加班"), entry(monday(2), mood="加班")]
        out = recall(hist, mood="加班")
        self.assertIn("不连续", out)
        self.assertNotIn("个连续周", out)

    def test_single_day_refuses_consecutive(self):
        out = recall([entry(monday(0), mood="加班")], mood="加班")
        self.assertIn("不可以说", out)


# ----------------------------------------------------------------------
# 6. 时间维度 · 价格变化
# ----------------------------------------------------------------------

class TestRecallPrice(unittest.TestCase):

    def test_unchanged_price(self):
        hist = [entry(monday(1), prices={"巨无霸": 25.5}),
                entry(monday(0), prices={"巨无霸": 25.5})]
        out = recall(hist)
        self.assertIn("与上次", out)
        self.assertIn("没变", out)

    def test_price_increase_must_be_disclosed(self):
        hist = [entry(monday(1), prices={"巨无霸": 25.5}),
                entry(monday(0), prices={"巨无霸": 26.5})]
        out = recall(hist)
        self.assertIn("涨了 1.00 元", out)
        self.assertIn("必须如实说涨", out)

    def test_price_decrease(self):
        hist = [entry(monday(1), prices={"巨无霸": 26.5}),
                entry(monday(0), prices={"巨无霸": 25.5})]
        out = recall(hist)
        self.assertIn("降了 1.00 元", out)

    def test_first_record_has_no_baseline(self):
        out = recall([entry(monday(0), prices={"巨无霸": 25.5})])
        self.assertIn("首次记录", out)

    def test_item_absent_from_previous_records(self):
        """上次没点过的东西，不应被拿来对比。"""
        hist = [entry(monday(1), prices={"巨无霸": 25.5}),
                entry(monday(0), prices={"新地": 12.0})]
        out = recall(hist)
        self.assertIn("新地：12.00 元（首次记录", out)

    def test_paid_amount_reported(self):
        hist = [entry(monday(0), prices={"巨无霸": 25.5}, paid=37.5)]
        self.assertIn("最近一次实付：37.50 元", recall(hist))

    def test_history_without_prices_does_not_crash(self):
        out = recall([entry(monday(1)), entry(monday(0))])
        self.assertIn("时间维度的事实", out)


# ----------------------------------------------------------------------
# 7. 边界与安全
# ----------------------------------------------------------------------

class TestEdges(unittest.TestCase):

    def test_empty_archive_says_unavailable(self):
        out = recall([])
        self.assertIn("暂不可用", out)

    def test_malformed_time_is_skipped(self):
        out = recall([entry("not-a-time"), entry(monday(0), prices={"巨无霸": 25.5})])
        self.assertIn("时间维度的事实", out)

    def test_canonical_data_is_not_touched(self):
        """测试必须使用临时档案，不能碰真实的 user_data/profile.json。"""
        real = ROOT / "user_data" / "profile.json"
        before = real.read_bytes() if real.exists() else None
        recall([entry(monday(0), prices={"巨无霸": 25.5})], mood="加班")
        after = real.read_bytes() if real.exists() else None
        self.assertEqual(before, after, "测试污染了真实档案")

    def test_example_config_contains_only_placeholder(self):
        """配置示例只能有占位符（参赛声明的信息安全要求）。"""
        cfg = ROOT / "mcp-config.example.json"
        text = cfg.read_text(encoding="utf-8")
        self.assertIn("${MCD_MCP_TOKEN}", text)
        self.assertNotIn("Bearer sk-", text)

    def test_cli_recall_runs_on_empty_archive(self):
        """CLI 层：空档案下 recall 应正常退出（退出码 0）。"""
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "profile.json"
            r = subprocess.run(
                [sys.executable, str(PROFILE_PATH), "--path", str(p), "recall"],
                capture_output=True, text=True, encoding="utf-8",
                env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("暂不可用", r.stdout)

    def test_cli_rejects_bad_price_format(self):
        """CLI 层：价格格式错误应以非零码退出。"""
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "profile.json"
            r = subprocess.run(
                [sys.executable, str(PROFILE_PATH), "--path", str(p),
                 "record", "--price", "巨无霸25.5"],
                capture_output=True, text=True, encoding="utf-8",
                env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
            )
            self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
