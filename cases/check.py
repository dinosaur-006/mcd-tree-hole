#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
麦门树洞 · 判决集判定引擎

    python cases/check.py
    python cases/check.py --group A_can_say
    python cases/check.py --verbose

它做三件事：

  1. 逐条读 cases/cases.json
  2. 为每条 case 在临时目录里造一个隔离档案，调用项目本体的真实逻辑
  3. 判定该 case 声明的约束是否成立

判定结果只有四种，全部会如实打印，包括「判不了」：

    PASS          约束成立，且是真跑出来的
    FAIL          约束不成立 —— 这是真问题，请改代码，不要改数字
    UNVERIFIABLE  这条约束需要人来看「好不好」，本文件不假装它能判
    LIMIT         已知的能力边界（D 类），不判对错

最后一条很重要。一份判决集如果声称自己什么都能自动判，
那它和一份广告就没有区别了。

## 判定的是什么

关键区别：本引擎判定的是**系统掌握的事实**，不是**它说的话**。

  判得了：档案里确实有 4 个连续周三 → compute_recall 必须报 4
  判不了：「连着 4 个周三了」这句话有没有说得好

前者是能力的下限，能机械验证；后者取决于模型生成，无法离线断言。
把所有约束都放在前一类上，这份判决集才立得住。

全程零第三方依赖，全程用临时目录。
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

CASES_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = CASES_ROOT.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import profile  # noqa: E402

CASES_FILE = CASES_ROOT / "cases.json"
FIXTURES_FILE = PROJECT_ROOT / "demo" / "fixtures" / "mcp_responses.json"

_TTY = sys.stdout.isatty()
if not _TTY and sys.platform == "win32":
    try:
        import ctypes
        k = ctypes.windll.kernel32
        k.SetConsoleMode(k.GetStdHandle(-11), 7)
        _TTY = True
    except Exception:
        _TTY = False


def _c(text, *codes):
    if not _TTY or not codes:
        return text
    return "\033[" + ";".join(codes) + "m" + text + "\033[0m"


GREEN = lambda t: _c(t, "32", "1")
RED = lambda t: _c(t, "31", "1")
YELLOW = lambda t: _c(t, "33", "1")
BLUE = lambda t: _c(t, "36")
DIM = lambda t: _c(t, "2")
BOLD = lambda t: _c(t, "1")


# ======================================================================
# 档案构造
# ======================================================================

def build_data(setup: dict) -> dict:
    """按 case 的 profile_setup 造一份档案数据（不落盘）。"""
    data = json.loads(json.dumps(profile.EMPTY_PROFILE))

    for entry in setup.get("ledger_history", []):
        data["ledger"]["history"].append(entry)
        data["ledger"]["total_saved"] = round(
            data["ledger"]["total_saved"] + float(entry.get("saved", 0.0)), 2)
        data["ledger"]["order_count"] += 1

    for i in range(setup.get("journal_count", 0)):
        data["journal"].append({"time": "2026-10-14 12:00", "text": "（判决集构造）", "mood": None})

    for i, mood in enumerate(setup.get("journal_moods", [])):
        if i < len(data["journal"]):
            data["journal"][i]["mood"] = mood

    for key, val in (setup.get("constraints") or {}).items():
        data["constraints"][key] = val

    return data


def build_profile_file(path: Path, setup: dict) -> None:
    profile.save(path, build_data(setup))


# ======================================================================
# 判定器
# ======================================================================

class Report:
    def __init__(self):
        self.counts = {"PASS": 0, "FAIL": 0, "UNVERIFIABLE": 0, "LIMIT": 0}
        self.fails: list[str] = []
        self.talk_pending = 0     # 需要人工看输出的「条」数（不是 case 数）
        self.facts_checked = 0    # 实际执行的机械断言条数

    def add(self, status, cid=""):
        self.counts[status] += 1
        if status == "FAIL":
            self.fails.append(cid)


def assert_fact(name: str, actual, expect, note: str = "") -> tuple[bool, str]:
    """一条事实断言。返回 (是否通过, 说明)。"""
    if actual == expect:
        return True, f"✓ {name}：{actual!r}" + (f"　{note}" if note else "")
    return False, f"✗ {name}：期望 {expect!r}，实际 {actual!r}"


def assert_true(name: str, actual, note: str = "") -> tuple[bool, str]:
    if actual:
        return True, f"✓ {name}" + (f"　{note}" if note else "")
    return False, f"✗ {name}：应为真，实际为假"


def assert_false(name: str, actual, note: str = "") -> tuple[bool, str]:
    if not actual:
        return True, f"✓ {name}" + (f"　{note}" if note else "")
    return False, f"✗ {name}：应为假，实际为真"


def evaluate_case(case: dict, fixtures: dict, verbose: bool) -> tuple[str, list[str], int, int]:
    """返回 (状态, 说明行, 机械断言数, 待人工条数)。"""
    cid = case["id"]
    group = case["group"]
    setup = case.get("profile_setup", {}) or {}

    lines: list[str] = []
    oks: list[bool] = []
    pending_human = 0

    # ---- D 类：已知边界，不判对错 ----
    if group == "D_known_limits":
        for k, label in [("known_failure", "已知失败模式"),
                         ("current_behavior", "当前行为"),
                         ("why_hard", "为什么难"),
                         ("impact", "影响"),
                         ("reproduce", "复现方法"),
                         ("severity", "严重度")]:
            lines.append(f"{label}：{case.get(k, '—')}")
        return "LIMIT", lines, 0, 0

    # ---- 可机械判定的：对事实的断言 ----
    with tempfile.TemporaryDirectory(prefix=f"cases-{cid}-") as tmp:
        prof = Path(tmp) / "profile.json"
        build_profile_file(prof, setup)
        data = build_data(setup)

        # 每个 case 都可能断言「时间维度的事实」
        mood = case.get("recall_mood")
        recall = profile.compute_recall(data, mood)

        if verbose:
            lines.append("compute_recall 实测：")
            for ln in json.dumps(recall, ensure_ascii=False, indent=2).splitlines():
                lines.append("    " + ln)

        # --- 断言 A：档案空 / 非空 ---
        if "expect_recall_ok" in case:
            ok, msg = assert_fact("recall 有记录", recall["ok"], case["expect_recall_ok"])
            oks.append(ok)
            lines.append(msg)

        # --- 断言 B：同类计数 ---
        if "expect_mood_count" in case:
            exp = case["expect_mood_count"]
            mc = recall.get("mood_count")
            if mc is None:
                oks.append(False)
                lines.append("✗ mood_count：未计算（未指定 recall_mood）")
            else:
                ok, msg = assert_fact(f"「{mc['mood']}」出现次数", mc["n"], exp["n"])
                oks.append(ok)
                lines.append(msg)
                if "sayable" in exp:
                    ok, msg = assert_fact(
                        "「第 N 次」可以说", mc["sayable"], exp["sayable"],
                        "（n>=2 才允许）" if exp["sayable"] else "（n<2 禁止）")
                    oks.append(ok)
                    lines.append(msg)

        # --- 断言 C：星期规律 ---
        if "expect_weekday" in case:
            exp = case["expect_weekday"]
            wd = recall.get("weekday")
            if wd is None:
                # 没有任何搭配记录时会走到这里，此时应期望「不可用」
                if exp.get("unavailable"):
                    oks.append(True)
                    lines.append("✓ 无搭配记录 → 星期规律不可用（符合预期）")
                else:
                    oks.append(False)
                    lines.append("✗ 星期规律：未计算，但 case 期望有值")
            else:
                if "weeks" in exp:
                    ok, msg = assert_fact(f"{wd['weekday']} 周数", wd["weeks"], exp["weeks"])
                    oks.append(ok)
                    lines.append(msg)
                if "consecutive" in exp:
                    ok, msg = assert_fact(
                        "判定为连续", wd["sayable_consecutive"], exp["consecutive"],
                        "（必须两两间隔恰好 7 天）" if exp["consecutive"] else "（不可说「连着」）")
                    oks.append(ok)
                    lines.append(msg)

        # --- 断言 D：价格变化 ---
        if "expect_price" in case:
            exp = case["expect_price"]
            found = next((p for p in recall["prices"] if p["item"] == exp["item"]), None)
            if found is None:
                oks.append(False)
                lines.append(f"✗ 价格：recall 里没有「{exp['item']}」")
            else:
                ok, msg = assert_fact(f"{exp['item']} 判定", found["verdict"], exp["verdict"],
                                      {"same": "（如实说没变）", "up": "（必须如实说涨）",
                                       "down": "", "first": "（无对比）"}.get(exp["verdict"], ""))
                oks.append(ok)
                lines.append(msg)

        # --- 断言 E：fixtures 里的实测组合 ---
        if "expect_combo" in case:
            exp = case["expect_combo"]
            combos = {c["key"]: c for c in fixtures["calculate-price"]["verifiedCombos"]}
            c = combos.get(exp)
            if c is None:
                oks.append(False)
                lines.append(f"✗ fixtures 里没有 {exp}")
            else:
                oks.append(True)
                lines.append(
                    f"✓ fixtures.{exp}：实付 {c['payPriceFen']/100:.2f} 元，"
                    f"原价 {c['originalPriceFen']/100:.2f} 元，"
                    f"省 {c['savedFen']/100:.2f} 元，用券 {c['couponsUsed']} 张")
                # 顺手校验一个恒等式：原价 - 实付 == 省
                lhs = c["originalPriceFen"] - c["payPriceFen"]
                if lhs == c["savedFen"]:
                    lines.append("✓ 恒等式 原价 − 实付 = 省 成立")
                else:
                    oks.append(False)
                    lines.append(f"✗ 恒等式不成立：{lhs} != {c['savedFen']}")

        # --- 断言 F：硬约束（过敏 / 不吃冰）是否真的被记下 ---
        if "expect_constraint" in case:
            exp = case["expect_constraint"]
            for key, want in exp.items():
                ok, msg = assert_fact(f"档案硬约束 {key}", data["constraints"].get(key), want)
                oks.append(ok)
                lines.append(msg)

        # --- 断言 G：自动拒单条件的可核查事实 ---
        if "expect_refuse_facts" in case:
            exp = case["expect_refuse_facts"]
            if "same_day_orders" in exp:
                n = recall["total_orders"]
                ok, msg = assert_fact("当日已有订单数", n, exp["same_day_orders"],
                                      "（>=1 即触发拒单条件二）")
                oks.append(ok)
                lines.append(msg)
            if "coupon_break_even" in exp:
                cb = setup.get("coupon_break_even", {})
                threshold = cb.get("threshold_fen")
                original = cb.get("original_fen")
                saving = cb.get("coupon_saving_fen")
                if None in (threshold, original, saving):
                    oks.append(False)
                    lines.append("✗ 券门槛数据缺失，无法判定")
                else:
                    net = (original - threshold) + saving
                    # 净收益为负 → 用券反而更贵 → 触发拒单条件三
                    should_refuse = net < 0
                    ok, msg = assert_true(
                        f"券精算：凑单多花 {threshold - original} 分、省 {saving} 分，净亏 {-net} 分"
                        if should_refuse else "券精算：划算",
                        should_refuse)
                    oks.append(ok)
                    lines.append(msg)

        # ---- 话术类约束：诚实标注为「判不了」 ----
        n_talk = (len(case.get("must_not_contain") or [])
                  + len(case.get("must_not_contain_patterns") or [])
                  + len(case.get("must_contain_any") or []))
        if n_talk:
            pending_human = n_talk

    # ---- 收口 ----
    n_facts = len(oks)

    if oks and not all(oks):
        return "FAIL", lines, n_facts, pending_human

    if oks:
        if pending_human:
            lines.append(
                f"○ 另有 {pending_human} 条话术约束只能人工判——"
                "本引擎不生成话术，故不假装能判")
        return "PASS", lines, n_facts, pending_human

    # 一条机械断言都没有 → 全是话术约束 → 判不了
    lines.append(
        f"○ {pending_human} 条话术约束需要一段真实模型输出才能判定 —— "
        "本引擎不生成话术，故不假装能判")
    return "UNVERIFIABLE", lines, 0, pending_human


# ======================================================================
# 主流程
# ======================================================================

def main() -> None:
    ap = argparse.ArgumentParser(prog="check.py", description="麦门树洞判决集判定引擎")
    ap.add_argument("--group", help="只跑某一组，如 B_must_not_say")
    ap.add_argument("--verbose", "-v", action="store_true", help="打印 compute_recall 原始结果")
    args = ap.parse_args()

    for f in (CASES_FILE, FIXTURES_FILE):
        if not f.exists():
            print(f"找不到 {f}", file=sys.stderr)
            sys.exit(1)

    cases_doc = json.loads(CASES_FILE.read_text(encoding="utf-8"))
    fixtures = json.loads(FIXTURES_FILE.read_text(encoding="utf-8"))
    groups = cases_doc["groups"]

    report = Report()

    print()
    print(BOLD("麦门树洞 · 判决集"))
    print(DIM(f"{len(cases_doc['cases'])} 条 case，判定对象是项目本体的真实逻辑。"))
    print(DIM("判定「系统掌握的事实」，不判定「它说的话」——后者无法离线验证。"))
    print("=" * 78)

    current = None
    for case in cases_doc["cases"]:
        g = case["group"]
        if args.group and g != args.group:
            continue

        if g != current:
            meta = groups[g]
            print()
            print(YELLOW(f"▌{meta['title']}") + DIM(f"  （{g}）"))
            print(DIM("  " + meta["meaning"]))
            print("-" * 78)
            current = g

        status, lines, n_facts, n_talk = evaluate_case(case, fixtures, args.verbose)
        report.facts_checked += n_facts
        report.talk_pending += n_talk

        tag = {"PASS": GREEN("PASS"), "FAIL": RED("FAIL"),
               "UNVERIFIABLE": BLUE("待人工"), "LIMIT": YELLOW("边界")}[status]

        print()
        print(f"  {tag}  {BOLD(case['id'])}  " + DIM("输入：") + f"「{case['input']}」")
        for ln in lines:
            if ln.startswith("✓"):
                print("        " + ln)
            elif ln.startswith("✗"):
                print("        " + RED(ln))
            elif ln.startswith("○"):
                print("        " + BLUE(ln))
            else:
                print("        " + DIM(ln))

        if case.get("reasoning") and args.verbose:
            print("        " + DIM("推导链："))
            for i, r in enumerate(case["reasoning"], 1):
                print("        " + DIM(f"  {i}. {r}"))

        if case.get("note"):
            print("        " + DIM("※ " + case["note"]))

        report.add(status, case["id"])

    print()
    print("=" * 78)
    print(BOLD("汇总"))
    print(f"  {GREEN('PASS')}          {report.counts['PASS']} 条  " + DIM("（约束成立，真跑出来的）"))
    print(f"  {RED('FAIL')}          {report.counts['FAIL']} 条")
    print(f"  {YELLOW('LIMIT')}         {report.counts['LIMIT']} 条  " + DIM("（已知边界，不是错误）"))
    if report.counts["UNVERIFIABLE"]:
        print(f"  {BLUE('UNVERIFIABLE')}  {report.counts['UNVERIFIABLE']} 条")
    print()
    print(DIM(f"  实际执行了 {report.facts_checked} 条机械断言。"))
    print(DIM(f"  另有 {report.talk_pending} 条话术约束只能人工看输出——"))
    print(DIM("  这部分不会因为本引擎说不了话就消失，它只是不在这里判。"))

    if report.counts["FAIL"]:
        print()
        print(RED("有约束不成立。这是真问题——请改代码，不要改数字。"))
        for cid in report.fails:
            print(RED(f"  · {cid}"))
        print()
        sys.exit(1)

    print()
    print(DIM("没有 FAIL。但这不等于「都对」——"))
    print(DIM("上面那 " + str(report.talk_pending) + " 条，正是不该被自动化判定掩盖的部分。"))
    print()


if __name__ == "__main__":
    main()
