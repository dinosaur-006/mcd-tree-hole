#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
麦门树洞 · 话术组装引擎

    python compose.py --mood 被掏空 --profile user_data/profile.json
    python compose.py --mood 被掏空 --json      # 输出结构化成分，供判决集断言
    python compose.py --list-slots              # 看所有成分与准入条件

## 为什么要有这个文件

在此之前，树洞说的话是「模型看着语录库现场编」。demo 里那六句写得好，
但第八句能不能写好，没有任何东西保证——那正是「AI 糊弄感」的来源。

这个文件把话术从**句子**变成**规则**：

    一句话 = 一组成分，每个成分有明确的准入条件

    承认    «把处境平铺出来»        无准入条件
    事实    «陈述一项档案里的事实»   必须有可算的事实，数字来自 compute_recall
    收束    «不折腾 / 不劝»         有准入条件，不满足就不出现

于是「第八句话」不再是编的：给定任何输入，「它该有哪些成分」是算出来的。
至于这句话读起来自不自然，仍然是模型的事——但**骨架不再是人写的**。

## 一条硬规矩

**本文件的任何成分，都不允许出现写死的数字。**

时间维度里的「4 次」「周三」「25.50 元」全部来自 compute_recall()。
写死一个数字，等于把这个文件变成更精致的硬编码——
那比不写它更糟，因为它看起来像在算。

## 与判决集的关系

`--json` 输出的是**结构化成分**，不是句子。判决集断言的就是这个结构：
哪个成分该出现、哪个成分不该出现、数字对不对。
句子本身好不好，判决集不判——它也判不了。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import profile  # noqa: E402


# ======================================================================
# 成分定义
# ======================================================================

@dataclass
class Slot:
    """一个成分。name 是成分名，text 是它的内容，why 是准入依据。"""
    name: str
    text: str
    why: str


@dataclass
class Utterance:
    """一次组装的结果。"""
    mood: str | None
    slots: list = field(default_factory=list)
    dropped: list = field(default_factory=list)   # 因准入不通过而没生成的成分
    facts: dict = field(default_factory=dict)      # compute_recall 的原始结果

    def text(self, sep: str = "") -> str:
        return sep.join(s.text for s in self.slots if s.text)


# ======================================================================
# 情绪类别 → 承认成分
# ======================================================================

# 每类给 3 条，按 hash 稳定选择（同一输入同一结果，可复现）。
# 这些是「承认」成分——只平铺处境，不评价、不打气、不给建议。
ACKNOWLEDGE = {
    "被掏空": [
        "今天这班，上得像被生活按在桌上摩擦。",
        "你已经把力气都用完了，剩下的部分不用再硬撑。",
        "累到不想讲话也没关系。",
    ],
    "委屈": [
        "白干也是干过了。",
        "有些事本来就不该由你扛。",
        "你解释了很多次，对方也没打算听懂。",
    ],
    "焦虑": [
        "你现在想的所有事，明天也不会变得更清楚。",
        "焦虑不会因为你想得更多而变小。",
        "深呼吸三次，不是为了放松，是为了确认你还在这儿。",
    ],
    "还得撑": [
        "还没到终点，但也别用跑的。",
        "你不是在拖延，你只是需要一点燃料。",
        "撑住不是唯一的选择，但如果你决定撑，这一份给你。",
    ],
    "烦躁": [
        "有些烦是讲不出理由的。",
        "你现在需要的不是建议，是一点脆的东西。",
        "坐不住就别坐了。",
    ],
    "开心": [
        "今天值得加个甜的。",
        "好日子就是要被记住。",
        "这种时候不需要我说话。",
    ],
    "难过": [
        "难过就是难过，不用急着好起来。",
        "说不出来的话，可以先不说。",
        "这件事确实让人不舒服。",
    ],
}

# 承载产品（锚点要用到，是「不变的东西」的具象）
CARRY = {
    "被掏空": "巨无霸",
    "委屈": "巨无霸",
    "焦虑": "热红茶",
    "还得撑": "咖啡",
    "烦躁": "麦乐鸡",
    "开心": "新地",
    "难过": "热红茶",
}


# ======================================================================
# 成分生成器 —— 每个都带准入条件
# ======================================================================

def _stable_choice(seq: list, seed: str):
    """按 seed 稳定选择。同一输入永远同一结果——这样才可复现、可断言。"""
    return seq[sum(ord(c) for c in seed) % len(seq)]


def slot_time_fact(recall: dict, mood: str | None) -> Slot | None:
    """事实成分：陈述档案里的时间维度事实。

    准入条件：至少能算出「第 N 次」或「连着 N 个周」中的一项。

    注意：**价格不在这里处理**。价格有「没变」与「涨了」两种去向，
    各自有独立成分（锚点 / 涨价），放在这里会和它们打架。
    """
    if not recall.get("ok"):
        return None

    parts = []
    whys = []

    # 1) 同类计数（最高优先级——它最像「记得你」）
    mc = recall.get("mood_count")
    if mc and mc.get("sayable"):
        parts.append(f"第 {mc['n']} 次了。")
        whys.append(f"mood_count={mc['n']}>=2")

    # 2) 星期规律
    wd = recall.get("weekday")
    if wd and wd.get("sayable_consecutive"):
        parts.append(f"连着 {wd['weeks']} 个{wd['weekday']}了。")
        whys.append(f"consecutive+weeks={wd['weeks']}")

    if not parts:
        return None

    return Slot(name="事实", text="".join(parts), why="; ".join(whys))


def slot_acknowledge(mood: str | None, seed: str) -> Slot | None:
    """承认成分。准入条件：识别出了情绪。

    没有情绪 → 返回 None（此时走中性承接句，不硬套语录）。
    """
    if not mood or mood not in ACKNOWLEDGE:
        return None
    text = _stable_choice(ACKNOWLEDGE[mood], seed)
    return Slot(name="承认", text=text, why=f"mood={mood}")


def slot_anchor(mood: str | None, recall: dict) -> Slot | None:
    """锚点成分：一个具体的不变之物。

    准入条件：
      1. 该情绪有承载产品
      2. **价格没有涨** —— 涨了还说「还是那个」，是自打嘴巴。
         涨价时这一条必须让位，改成如实陈述（见 slot_price_honesty）。

    锚点说的是「东西没变」，不是「你会好起来」——后者是打气，禁用。
    """
    if not mood or mood not in CARRY:
        return None

    # 价格涨了 → 锚点不能说「还是那个」
    for p in recall.get("prices", []):
        if p["verdict"] == "up":
            return None

    product = CARRY[mood]

    # 价格没变过 → 锚点可以带上「一分没涨」，这比空说「还是那个」更有力
    for p in recall.get("prices", []):
        if p["verdict"] == "same":
            return Slot(
                name="锚点",
                text=f"{product}还是 {p['current']:.2f}，一分没涨。",
                why=f"carry={product}; price same={p['current']}",
            )

    return Slot(name="锚点", text=f"{product}还是那个{product}。", why=f"carry={product}")


def slot_price_honesty(mood: str | None, recall: dict) -> Slot | None:
    """涨价如实说成分。

    准入条件：最近一次比价发现涨价。
    这是本类语录唯一的价值来源——一个肯告诉你「涨了 1 块」的地方，
    说「没变」的时候才可信。

    与 slot_anchor 互斥：涨价时锚点不出现，由这一条接管。
    """
    for p in recall.get("prices", []):
        if p["verdict"] == "up":
            return Slot(
                name="涨价",
                text=f"{p['item']}涨了 {p['diff']:.2f}，现在 {p['current']:.2f}。这次不瞒你。",
                why=f"price up diff={p['diff']}",
            )
    return None


def slot_hold(mood: str | None, recall: dict) -> Slot | None:
    """收束成分：不折腾 / 不劝。

    准入条件：来访次数够多（mood_count >= 3）。
    次数不够就不说这句——第一次来的人，说「今天不劝你换」是莫名其妙的。
    """
    mc = recall.get("mood_count")
    if not mc or mc.get("n", 0) < 3:
        return None
    return Slot(name="收束", text="今天不劝你换，就这个。", why=f"mood_count={mc['n']}>=3")


def slot_no_order(mood: str | None) -> Slot | None:
    """不点单成分。

    准入条件：情绪类别是「难过」——这一类的正确出口是不点单，不是硬推产品。
    """
    if mood != "难过":
        return None
    return Slot(name="不点单", text="这顿不用点，我在这。", why="mood=难过 → 走不点单出口")


# ======================================================================
# 组装的硬门禁 —— 说完之后必须自查
# ======================================================================

# 出现在任何位置都不允许的词（来自 guardrails 第六节）
BANNED = [
    "加油", "会好的", "想开点", "我理解你", "建议你", "你要相信",
    "一切都会好", "没关系", "没事的", "别难过", "开心一点",
    "检测到您", "您目前处于", "根据您的情绪状态",
    "为了你好",
]


def audit(text: str) -> list[str]:
    """输出前自查。返回踩到的禁用词列表（空=通过）。"""
    return [w for w in BANNED if w in text]


# ======================================================================
# 主组装函数
# ======================================================================

def compose(mood: str | None, data: dict, seed: str | None = None) -> Utterance:
    """把情绪 + 档案组装成一句话。

    这是「第八句话」的定义：给定任何输入，输出由规则决定。
    """
    seed = seed if seed is not None else (mood or "")
    recall = profile.compute_recall(data, mood)

    result = Utterance(mood=mood, facts=recall)

    # 候选成分（按顺序）
    # 注意锚点与涨价互斥：涨价时锚点返回 None，由涨价成分接管。
    candidates = [
        slot_acknowledge(mood, seed),
        slot_time_fact(recall, mood),
        slot_anchor(mood, recall),
        slot_price_honesty(mood, recall),
        slot_hold(mood, recall),
        slot_no_order(mood),
    ]

    # 每个成分要么进 slots，要么记进 dropped（并附原因）
    reasons = {
        "承认": "未识别出情绪 → 走中性承接句，不硬套语录",
        "事实": "档案里算不出「第 N 次」或「连着 N 个周」→ 不生成（绝不编造）",
        "锚点": "该情绪无承载产品，或价格涨了（涨了还说「还是那个」是自打嘴巴）",
        "涨价": "没有检测到涨价",
        "收束": "来访次数 < 3 → 第一次来不适合说「今天不劝你换」",
        "不点单": "非「难过」类 → 正常推荐，不走不点单出口",
    }
    names = ["承认", "事实", "锚点", "涨价", "收束", "不点单"]
    for name, slot in zip(names, candidates):
        if slot is None:
            result.dropped.append({"name": name, "why": reasons[name]})
        else:
            result.slots.append(slot)

    return result


def compose_with_audit(mood: str | None, data: dict, seed: str | None = None):
    """组装 + 自查。返回 (utterance, 踩到的禁用词列表)。"""
    u = compose(mood, data, seed)
    return u, audit(u.text())


# ======================================================================
# CLI
# ======================================================================

def cmd_list_slots() -> None:
    print("成分定义与准入条件")
    print("=" * 70)
    rows = [
        ("承认", "把用户的处境平铺出来，不评价、不打气、不给建议",
                  "识别出情绪（七类之一）"),
        ("事实", "陈述一项来自本地档案的时间维度事实",
                  "compute_recall 至少算出一项（第 N 次 / 连着 N 个周 / 价格变化）"),
        ("锚点", "指出一个具体的不变之物",
                  "该情绪在 CARRY 表里有配对产品"),
        ("收束", "表态不折腾——不劝你换",
                  "同一情绪出现次数 >= 3"),
        ("不点单", "明确说这顿不用点",
                  "情绪类别为「难过」（正确出口是不点单）"),
    ]
    for name, what, when in rows:
        print()
        print(f"  {name}")
        print(f"    作用：{what}")
        print(f"    准入：{when}")

    print()
    print("情绪类别：" + "、".join(ACKNOWLEDGE.keys()))
    print()
    print("硬门禁（任何成分都不允许出现）：")
    print("  " + "、".join(BANNED))


def main() -> None:
    ap = argparse.ArgumentParser(prog="compose.py", description="麦门树洞话术组装引擎")
    ap.add_argument("--mood", help="情绪类别，如 被掏空")
    ap.add_argument("--profile", type=Path, default=profile.DEFAULT_PATH,
                    help=f"档案路径，默认 {profile.DEFAULT_PATH}")
    ap.add_argument("--seed", help="稳定选择的种子，默认用 mood")
    ap.add_argument("--json", action="store_true", help="输出结构化成分（判决集用）")
    ap.add_argument("--list-slots", action="store_true", help="列出所有成分与准入条件")
    args = ap.parse_args()

    if args.list_slots:
        cmd_list_slots()
        return

    data = profile.load(args.profile)
    u, hits = compose_with_audit(args.mood, data, args.seed)

    if args.json:
        out = asdict(u)
        out["_text"] = u.text()
        out["_banned_hits"] = hits
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    print()
    print("组装结果")
    print("=" * 70)
    print()
    print("  " + u.text())
    print()
    print("成分明细：")
    for s in u.slots:
        print(f"  [出现] {s.name}：{s.text}")
        print(f"         依据：{s.why}")
    if u.dropped:
        print()
        print("未生成的成分：")
        for d in u.dropped:
            print(f"  [不出现] {d['name']}：{d['why']}")
    print()
    if hits:
        print(f"  ✗ 自查不通过，出现禁用词：{'、'.join(hits)}")
        sys.exit(1)
    print("  ✓ 自查通过，未出现任何禁用词")


if __name__ == "__main__":
    main()
