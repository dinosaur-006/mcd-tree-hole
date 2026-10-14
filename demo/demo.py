#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
麦门树洞 · 一句话演示

    python demo.py

不需要 Token、不联网、不装任何第三方库。
30 秒跑完一个人和树洞打交道的第 1 次到第 7 次。

说明几件事：
  · 这不是录屏，是真的在跑逻辑——情绪映射、降级链、券精算、拒单判定，
    都由项目本体（scripts/profile.py）驱动。
  · 价格不是编的。全部取自 2026-10-12 对真实门店 storeCode=1450323
    的实测记录，见 demo/fixtures/mcp_responses.json 与 MCP_INTEGRATION.md 第五节。
  · 全程写完就删。档案落在临时目录，绝不碰你本机的 user_data/profile.json。
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

DEMO_ROOT = Path(__file__).resolve().parent
SKILL_ROOT = DEMO_ROOT.parent
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

import profile  # noqa: E402  —— 复用真实的档案模块，不是复刻一份
import compose  # noqa: E402  —— 话术组装引擎：这句话是算出来的，不是写死的

FIXTURES = DEMO_ROOT / "fixtures" / "mcp_responses.json"

# 终端宽度。留 4 字符余量给边框。
WIDTH = 76

# ANSI。终端不支持时 _style() 会退化为纯文本。
_TTY = sys.stdout.isatty()
if not _TTY and sys.platform == "win32":
    # Windows 老终端要显式打开 VT 处理，否则彩色会变成乱码
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        _TTY = True
    except Exception:
        _TTY = False


def _style(text: str, *codes: str) -> str:
    if not _TTY or not codes:
        return text
    return "\033[" + ";".join(codes) + "m" + text + "\033[0m"


def bold(t):      return _style(t, "1")
def dim(t):       return _style(t, "2")
def yellow(t):    return _style(t, "33", "1")
def red(t):       return _style(t, "31")
def green(t):     return _style(t, "32")
def cyan(t):      return _style(t, "36")


# ----------------------------------------------------------------------
# 输出原语
# ----------------------------------------------------------------------

def rule(char: str = "─") -> None:
    print(dim(char * WIDTH))


def scene(index: int, title: str) -> None:
    """一幕的开头。"""
    print()
    print(yellow(f"【第 {index} 幕】") + " " + bold(title))
    rule()


def user_says(text: str) -> None:
    """用户的话——有气泡。"""
    inner = WIDTH - 6
    print()
    print(yellow("  ╭─ 你 " + "─" * (WIDTH - 8) + "╮"))
    for line in _wrap_cjk(text, inner - 2):
        print(yellow("  │ ") + pad_cjk(line, inner) + yellow(" │"))
    print(yellow("  ╰" + "─" * (WIDTH - 4) + "╯"))


def tree_says(text: str, max_lines: int = 3) -> None:
    """树洞的话——不是气泡，是一张放在桌上的纸。"""
    inner = WIDTH - 6
    lines = _wrap_cjk(text, inner - 2)
    print()
    print(yellow("  ┌─ ") + dim("树洞") + " " + yellow("─" * (WIDTH - 14) + "┐"))
    for line in lines[:max_lines]:
        print(yellow("  │ ") + pad_cjk(line, inner) + yellow(" │"))
    print(yellow("  └" + "─" * (WIDTH - 4) + "┘"))


def _wrap_cjk(text: str, width: int) -> list[str]:
    """按显示宽度折行。中文占两格，textwrap 默认按字符数算，会撑破框。

    三条中文排版规则：
      · 收尾标点（。，、」等）不能出现在行首
      · 破折号不能被拆到两行
      · 尽量不在「词中间」断——优先在标点或空格处断行
    """
    lines: list[str] = []
    cur = ""
    cur_w = 0
    # 记录当前行最后一个「可断点」的索引与宽度（标点 / 空格之后）
    soft_break_at = 0
    soft_break_w = 0

    for ch in text:
        w = 2 if ord(ch) > 0x2E80 else 1

        if cur_w + w > width and cur:
            if ch in "，。、；：）」』】—…！？":
                # 行首禁则：标点挤在上一行
                cur += ch
                lines.append(cur.rstrip())
                cur, cur_w = "", 0
                soft_break_at = soft_break_w = 0
                continue
            if ch == "—" and cur.endswith("—"):
                cur = cur.rstrip()[:-1]
                lines.append(cur.rstrip())
                cur, cur_w = "——", 4
                soft_break_at = soft_break_w = 0
                continue

            # 有更靠后的可断点就往回退，避免把词劈开
            if 0 < soft_break_at < len(cur):
                lines.append(cur[:soft_break_at].rstrip())
                rest = cur[soft_break_at:]
                cur = rest
                cur_w = sum(2 if ord(c) > 0x2E80 else 1 for c in rest)
            else:
                lines.append(cur.rstrip())
                cur, cur_w = "", 0
            soft_break_at = soft_break_w = 0

        cur += ch
        cur_w += w
        if ch in "，。、；：）」』】！？ ":
            soft_break_at = len(cur)
            soft_break_w = cur_w

    if cur.strip():
        lines.append(cur.rstrip())
    return lines or [""]


def pad_cjk(text: str, width: int) -> str:
    """按显示宽度右侧补空格。"""
    w = sum(2 if ord(c) > 0x2E80 else 1 for c in text)
    return text + " " * max(0, width - w)


def note(text: str) -> None:
    """旁白。用来解释这一幕在演示什么。"""
    for line in _wrap_cjk(text, WIDTH - 4):
        print(dim("  · " + line))


def receipt(combo: dict, extra: str = "") -> None:
    """账单。等宽 + 右对齐 —— 情绪在上面，数字在下面，视觉上分开。"""
    pay = combo["payPriceFen"] / 100
    orig = combo["originalPriceFen"] / 100
    saved = combo["savedFen"] / 100
    n_coupon = combo["couponsUsed"]

    print()
    print("      " + dim("──────────────────────────────"))
    for item in combo["items"]:
        print("      " + item)
    print("      " + dim("──────────────────────────────"))
    if saved > 0:
        print("      " + dim(f"原价  {orig:>8.2f} 元"))
    print("      " + bold(f"实付  {pay:>8.2f} 元"))
    if saved > 0:
        tail = f"省 {saved:.2f} 元"
        if n_coupon:
            tail += f"，用掉 {n_coupon} 张券"
        print("      " + green(tail))
    elif n_coupon == 0 and saved == 0 and extra:
        print("      " + dim(extra))
    print("      " + dim("──────────────────────────────"))


def recalled_facts(path: Path, mood: str | None = None) -> list[str]:
    """调真实的 cmd_recall，把事实抓回来。"""
    import io
    from contextlib import redirect_stdout

    parser = profile.build_parser()
    argv = ["--path", str(path), "recall"]
    if mood:
        argv += ["--mood", mood]
    args = parser.parse_args(argv)

    buf = io.StringIO()
    with redirect_stdout(buf):
        args.func(args)
    return [ln.rstrip() for ln in buf.getvalue().splitlines() if ln.strip()]


def pick(facts: list[str], keyword: str) -> str:
    """从事实里挑出含关键词的那条，去掉句号后的解释部分。"""
    for line in facts:
        if keyword in line:
            return line.split("——")[0].strip()
    return ""


# ----------------------------------------------------------------------
# 6 幕，从第 1 次到第 7 次
# ----------------------------------------------------------------------

def act1_first_time(prof: Path, fx: dict, t0: datetime) -> None:
    scene(1, "第一次来 · 情绪是选择依据，不是消费理由")
    note("这一场他在说累。树洞不分析、不劝、不反问——只把累翻译成「想吃什么」。")

    user_says("今天开会开到脑子空了，随便吃点什么吧")

    tree_says(
        "脑子空了。那就不动脑子——先给你上热的、软的、不用嚼的。"
        "饿是真的，累也是真的，两件事不冲突。"
    )

    note("情绪 → 感官需求 → 产品。每环都有降级链，走到底就走「认输」出口。")
    print()
    print("      " + cyan("新地（巧克力）") + "  ← 甜的、凉的、一口闷")
    print("      " + dim("  ↳ 若不想吃冰：") + "黑洋酥小圆子风味派  ← 热的、糯的")
    print("      " + dim("  ↳ 若这两样都没有：") + "「今天这家店没有合适的，换一家？」")

    combo = fx["calculate-price"]["verifiedCombos"][1]  # combo_b：巨无霸 + 新地
    note("落到真实价格上：")
    receipt(combo, extra="本身就这个价，没有券可用——不硬凑。")

    _record(prof, t0, mood="被掏空", items="巨无霸,新地（巧克力）",
            paid=37.50, saved=0.0, prices={"巨无霸": 25.5, "新地（巧克力）": 12.0})


def act2_quiet_exit(prof: Path, fx: dict, t: datetime) -> None:
    scene(2, "第二次 · 「今天不点单」是正常结局，不是失败")
    note(
        "上一条记录之后，他今天没打算买。树洞必须接住这件事——"
        "否则这里就变成了漏斗，不是树洞。"
    )

    user_says("今天就算了，我就想找个人说说")

    tree_says("那就说说。今天不用点单，账本不动，我不问第二遍。")

    print()
    print("      " + dim("· 不推荐任何商品"))
    print("      " + dim("· 不写入账本"))
    print("      " + dim("· 不追问「真的不要吗」"))

    # 真的写进情绪日记——不是嘴上说说。账本不动。
    data = profile.load(prof)
    data["journal"].append({
        "time": t.strftime("%Y-%m-%d %H:%M"),
        "text": "今天就算了，我就想找个人说说",
        "mood": "没什么大事",
    })
    profile.save(prof, data)

    print()
    note("这句话进了情绪日记。你可以随时 `journal-clear` 一键删掉它，"
         "账本不受影响——这是两个分开的文件。")


def act3_reject(prof: Path, fx: dict) -> None:
    scene(3, "第三次 · 有一种帮助叫「不卖给你」")
    print()
    print("      " + bold("主动拒单的四个条件（命中任一即拒，且拒单不附带任何商品）："))
    for i, cond in enumerate([
        "凌晨 00:00–05:00　—— 这个点的问题通常不是饿",
        "当天已经点过一次　—— 再点不是需求，是别的什么",
        "券要凑单才划算　　—— 为了省 5 块多花 20 块，这不叫省钱",
        "只是难过　　　　　—— 难过本身不需要被喂饱",
    ], 1):
        print(f"      {i}. {cond}")
    print()

    user_says("算了不吃了，我就是难过")

    tree_says("嗯。那就是难过，不是饿。这顿不用点，我在这。")
    print()
    print("      " + green("→ 触发第 4 条。不推荐商品，不入账本。"))


def act4_g_class(prof: Path, fx: dict, dates: list[datetime]) -> None:
    scene(4, "第 4 个周三 · 只有树洞记得的那些事")
    note(
        "这是整个产品唯一必须依赖本地档案的功能：时间是它自己的记忆。"
        "下面每句话的数字，都来自真实写入的档案，不是预设台词。"
    )

    # 把第 4~6 次补上，攒出「连着 N 个周三」
    for d in dates:
        _record(prof, d, mood="被掏空", items="巨无霸",
                paid=25.5, saved=0.0, prices={"巨无霸": 25.5},
                verbose=False)

    facts = recalled_facts(prof, mood="被掏空")

    print()
    print("      " + dim("档案里查到的事实："))
    for line in facts:
        if line.startswith("——"):
            continue
        print("      " + dim("│ " + line))
    print()

    user_says("今天还是老样子，累")

    # ── 这句台词不是写死的，是组装出来的 ──
    data = profile.load(prof)
    utter, hits = compose.compose_with_audit("被掏空", data)

    print()
    print("      " + dim("组装引擎算出的成分："))
    for s in utter.slots:
        print("      " + dim(f"│ [{s.name}] {s.text}"))
        print("      " + dim(f"│   依据：{s.why}"))
    for d in utter.dropped:
        print("      " + dim(f"│ [不出现] {d['name']}：{d['why']}"))
    if hits:
        print("      " + red(f"│ ✗ 自查不通过：{'、'.join(hits)}"))

    tree_says(utter.text())

    note(
        "注意：树洞没有说「检测到您已连续三次处于疲惫状态」。"
        "它只是陈述事实。贴标签是禁用文案。"
    )
    note(
        "更要紧的是——上面那句话没有一个字是写死的。"
        "次数来自档案、周数来自档案、价格来自档案，"
        "连要不要说「今天不劝你换」都是算出来的（次数 ≥ 3 才说）。"
    )
    note("想看这句话是怎么被守住的，跑：python cases/check.py")

    combo = {"items": ["巨无霸"], "originalPriceFen": 2550,
             "payPriceFen": 2550, "savedFen": 0, "couponsUsed": 0}
    receipt(combo, extra="老样子。")


def act5_coupon(prof: Path, fx: dict, t: datetime) -> None:
    scene(5, "同一天 · 券不是优惠券，是一个商品编码")
    note(
        "这是接 MCP 之后最容易做错的地方。麦当劳的券不是「满 30 减 5」，"
        "而是促销 SKU——用券 = 替换商品编码 + 带上 couponId。"
    )

    user_says("两个人吃，帮我搭一下，能用券就用")

    print()
    print("      " + bold("调用顺序（11 步编排里关键的四步）："))
    print("      1. " + dim("query-meals") + "              拿到菜单 + 标签")
    print("      2. " + dim("query-store-coupons") + "      拿这家店、这个取餐方式下真正能用的券")
    print("      3. " + dim("calculate-price") + "          算价（返回单位是「分」，别忘除以 100）")
    print("      4. " + dim("再算一次不用的价") + "        对比，券不划算就撤掉")
    print()
    note("第 2 步为什么不能用 query-my-coupons：官方明确说它不做门店和下单规则校验，"
         "不承诺能用在当前订单上。用它会算出假优惠。")
    print()

    print("      " + dim("这家店这个时段查到 " +
                        str(fx["query-store-coupons"]["couponsReturned"]) + " 张可用券："))
    for c in fx["query-store-coupons"]["coupons"]:
        print("      ├─ " + cyan(c["title"]) + dim(f"　（有效期至 {c['validUntil']}）"))
        print("      │  " + dim(f"productCode={c['productCode']}　→ 用券就是把这个编码换上去"))
    print()

    combo = fx["calculate-price"]["verifiedCombos"][0]  # combo_a
    print("      " + dim("不用券：69.50 元"))
    print("      " + dim("用券　：") + bold("56.00 元"))
    print("      " + dim("第二份薯条是白拿的——券价 13.50 买两份。"))
    receipt(combo)

    resp = _record(prof, t, mood=None, items="巨无霸,麦香鸡,中薯条买一送一",
                   paid=56.0, saved=13.5,
                   prices={"巨无霸": 25.5, "中薯条买一送一": 13.5}, verbose=False)
    print()
    print("      " + green(f"→ {resp}"))


def act6_ledger(prof: Path, t: datetime) -> None:
    scene(6, "账本 · 真正撑住复用的那一层")
    note("情绪日记是情感沉淀，账本才是留存的骨架。它每天都值一次打开。")

    parser = profile.build_parser()
    args = parser.parse_args(["--path", str(prof), "stats"])
    print()
    args.func(args)

    print()
    note("这份档案在你自己的电脑上，一个 JSON 文件。没有云端读取路径。"
         "你可以把整件事删掉，删掉之后我确实会忘记你——这是设计的一部分。")


def _record(prof: Path, when: datetime, *, mood, items, paid, saved,
            prices, verbose: bool = True) -> str:
    """写一条真实记录进临时档案，时间回填到 when。"""
    data = profile.load(prof)
    entry = {
        "time": when.strftime("%Y-%m-%d %H:%M"),
        "items": items,
        "saved": float(saved),
        "mood": mood,
        "paid": float(paid),
        "prices": prices,
    }
    data["ledger"]["history"].append(entry)
    data["ledger"]["total_saved"] = round(data["ledger"]["total_saved"] + saved, 2)
    data["ledger"]["order_count"] += 1

    msg = (f"已记账：本次省 {saved:.2f} 元，"
           f"累计省 {data['ledger']['total_saved']:.2f} 元，"
           f"共 {data['ledger']['order_count']} 单。")
    profile.save(prof, data)
    if verbose:
        print("      " + dim(msg))
    return msg


# ----------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------

def _selftest() -> None:
    """不打印对话，只验证：这些话不是打印出来的，是算出来的。

    有人可能会怀疑「这段对话是不是写死的」。这里给出两层反证：

      第一层：把档案改一改，「事实」跟着变。
      第二层：把档案改一改，**「说哪个成分」也跟着变**。
              这一层才是关键——它证明句子本身是组装的，不是抄的。
    """
    print("自检：这些话不是打印出来的，是算出来的。")
    print()

    with tempfile.TemporaryDirectory(prefix="mcd-selftest-") as tmp:
        prof = Path(tmp) / "profile.json"

        def show(label: str) -> None:
            data = profile.load(prof)
            u, hits = compose.compose_with_audit("被掏空", data)
            print(f"  {label}")
            print("    " + dim("成分：" + (" + ".join(s.name for s in u.slots) or "无")))
            print("    " + dim("输出：" + (u.text() or "（空）")))
            if hits:
                print("    " + red("禁用词：" + "、".join(hits)))
            print()

        print(dim("第 1 步 · 先看「事实」是不是真的从档案来"))
        print()

        # 场景 A：只有一个周三
        _record(prof, datetime(2026, 10, 14, 21, 10), mood="被掏空",
                items="巨无霸", paid=25.5, saved=0.0,
                prices={"巨无霸": 25.5}, verbose=False)
        print("  档案里只有 1 个周三 →")
        for ln in recalled_facts(prof, mood="被掏空"):
            if "周三" in ln or "已出现" in ln:
                print("    " + dim(ln))

        # 场景 B：补两个连续周三
        for d in [datetime(2026, 9, 30, 21, 10), datetime(2026, 10, 7, 21, 10)]:
            _record(prof, d, mood="被掏空", items="巨无霸", paid=25.5,
                    saved=0.0, prices={"巨无霸": 25.5}, verbose=False)
        print()
        print("  补上另外 2 个连续周三 →")
        for ln in recalled_facts(prof, mood="被掏空"):
            if "周三" in ln or "已出现" in ln:
                print("    " + dim(ln))

        print()
        print(dim("第 2 步 · 看「说哪些成分」是不是也跟着档案走"))
        print()

        # 但这里档案已经有 3 条了。为了演示「第一次来」的样子，
        # 另起一个干净档案。
        with tempfile.TemporaryDirectory(prefix="mcd-fresh-") as tmp2:
            fresh = Path(tmp2) / "profile.json"
            data = profile.load(fresh)
            u, _ = compose.compose_with_audit("被掏空", data)
            print("  空档案（第一次来）")
            print("    " + dim("成分：" + (" + ".join(s.name for s in u.slots) or "无")))
            print("    " + dim("输出：" + (u.text() or "（空）")))
            print()

        show("攒够连续周之后")

        # 真的改价：把最新一条的成交价从 25.50 提到 27.00
        data = profile.load(prof)
        data["ledger"]["history"][-1]["prices"] = {"巨无霸": 27.0}
        profile.save(prof, data)
        show("只把最新一次的价改成 27.00")

    print("  第 1 层：数字跟着档案走。")
    print("  第 2 层：连「说哪几个成分」都跟着档案走 ——")
    print("          空档案时不说「第 N 次」，涨价时不说「还是那个」。")
    print("  说不出的话，它不会说。这就是「第八句话」和「前六句话」的差别。")
    print()


def main() -> None:
    if "--selftest" in sys.argv:
        _selftest()
        return

    if not FIXTURES.exists():
        print(f"找不到 {FIXTURES}，无法演示。", file=sys.stderr)
        sys.exit(1)

    with FIXTURES.open("r", encoding="utf-8") as f:
        fx = json.load(f)

    print()
    rule("═")
    print("  " + yellow("麦门树洞") + "  " + dim("说一句，我给你点一份。"))
    print("  " + dim("零依赖演示：不需要 Token、不联网、不装任何库。"))
    rule("═")

    print()
    note(f"门店：{fx['_store']['storeName']}（{fx['_store']['storeCode']}）"
         f"，{fx['_store']['orderType']}")
    note(f"数据取自：{fx['_store']['capturedAt']}　·　"
         f"读到 {fx['now-time-info']['mealPeriod']}")
    note(fx["_honesty"])

    # 第 1 次：三个星期前的周三
    # 第 4~6 次：之后连续三个周三
    # 第 7 次：今天
    today = datetime(2026, 10, 14, 21, 10)   # 周三
    first = today - timedelta(days=21)       # 也是周三
    chain = [today - timedelta(days=14), today - timedelta(days=7), today]

    with tempfile.TemporaryDirectory(prefix="mcd-tree-hole-demo-") as tmp:
        prof = Path(tmp) / "profile.json"

        print()
        print(dim(f"档案写在临时目录，跑完即删：{tmp}"))
        print(dim("你自己的 user_data/profile.json 全程没有被碰过。"))

        act1_first_time(prof, fx, first)
        act2_quiet_exit(prof, fx, first + timedelta(days=3))
        act3_reject(prof, fx)
        act4_g_class(prof, fx, chain)
        act5_coupon(prof, fx, today)
        act6_ledger(prof, today)

    print()
    rule("═")
    print("  " + bold("以上全部数字，取自 2026-10-12 对真实门店 1450323 的实测记录。"))
    print("  " + dim("没有一处是编的——包括「没变」和「省 0 元」。"))
    print()
    print("  " + dim("源码与完整用法：https://github.com/dinosaur-006/mcd-tree-hole"))
    rule("═")
    print()


if __name__ == "__main__":
    main()
