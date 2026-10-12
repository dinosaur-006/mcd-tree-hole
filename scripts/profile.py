#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
麦门树洞 · 本地档案模块

管理三样东西，全部只存在用户本机，不上传、不入库、无云端读取路径：

  1. 硬约束与软偏好 —— 驱动第一层过滤与第二层排序
  2. 口味档案与省钱账本 —— 跨次累积，构成留存机制
  3. 情绪日记 —— 情感沉淀，支持一键清空
  4. 时间维度的事实 —— 第几次、上次点的什么、价格变没变（驱动 G 类语录）

用法示例：
    python profile.py show
    python profile.py set --allergy 花生 --no-ice --budget-max 40
    python profile.py record --saved 13.5 --paid 56 --items "巨无霸,麦香鸡" \
        --price "巨无霸=25.5" --price "麦香鸡=17" --mood 疲惫
    python profile.py journal-add "今天上班又白干了"
    python profile.py journal-clear
    python profile.py stats
    python profile.py recall --mood 疲惫
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = SKILL_ROOT / "user_data" / "profile.json"

SCHEMA_VERSION = 1

EMPTY_PROFILE = {
    "version": SCHEMA_VERSION,
    "constraints": {
        # 命中即从候选池剔除，不参与任何权衡
        "allergies": [],        # 过敏原，如 ["花生", "乳制品"]
        "religious": None,      # 宗教或民族饮食限制，如 "清真" / "素食"
        "no_ice": False,        # 不吃冰（生理期 / 肠胃）
        "sugar_control": False, # 控糖
        "sodium_control": False,# 控钠
        "caffeine_after_21": True,  # 21:00 后不推荐含咖啡因饮品
        "budget_max": None,     # 单次预算上限（元）
    },
    "preferences": {
        # 仅影响排序，不改变候选集合
        "taste": [],            # 口味倾向，如 ["辣", "甜"]
        "usual_people": None,   # 常见用餐人数
        "calorie_target": None, # 单次热量目标（kcal）
    },
    "favorites": [],            # 常点组合，用于一键复购
    "ledger": {
        "total_saved": 0.0,
        "order_count": 0,
        "history": [],
    },
    "journal": [],
}


def load(path: Path) -> dict:
    if not path.exists():
        return json.loads(json.dumps(EMPTY_PROFILE))
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[错误] 档案读取失败：{exc}", file=sys.stderr)
        sys.exit(1)

    # 补齐缺失字段，兼容旧版本档案
    for key, value in EMPTY_PROFILE.items():
        if key not in data:
            data[key] = json.loads(json.dumps(value))
        elif isinstance(value, dict):
            for sub_key, sub_value in value.items():
                data[key].setdefault(sub_key, sub_value)
    return data


def save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


# ----------------------------------------------------------------------
# 命令实现
# ----------------------------------------------------------------------

def cmd_show(args) -> None:
    data = load(args.path)
    print(json.dumps(data, ensure_ascii=False, indent=2))


def cmd_set(args) -> None:
    data = load(args.path)
    c = data["constraints"]

    if args.allergy:
        for item in args.allergy:
            if item not in c["allergies"]:
                c["allergies"].append(item)
    if args.no_allergy:
        c["allergies"] = [a for a in c["allergies"] if a not in args.no_allergy]
    if args.religious is not None:
        c["religious"] = args.religious or None
    if args.no_ice is not None:
        c["no_ice"] = args.no_ice
    if args.sugar is not None:
        c["sugar_control"] = args.sugar
    if args.sodium is not None:
        c["sodium_control"] = args.sodium
    if args.budget_max is not None:
        c["budget_max"] = args.budget_max
    if args.taste:
        for item in args.taste:
            if item not in data["preferences"]["taste"]:
                data["preferences"]["taste"].append(item)
    if args.people is not None:
        data["preferences"]["usual_people"] = args.people
    if args.calorie is not None:
        data["preferences"]["calorie_target"] = args.calorie

    save(args.path, data)
    print("档案已更新。")


def cmd_favorite(args) -> None:
    data = load(args.path)
    if args.remove:
        data["favorites"] = [f for f in data["favorites"] if f.get("name") != args.remove]
        save(args.path, data)
        print(f"已移除常点组合：{args.remove}")
        return
    if not args.name:
        print("[错误] 新增常点组合需要 --name", file=sys.stderr)
        sys.exit(1)
    data["favorites"].append({"name": args.name, "items": args.items or []})
    save(args.path, data)
    print(f"已记录常点组合：{args.name}")


def parse_prices(raw_items) -> dict:
    """把 ["巨无霸=25.5", "新地=12"] 解析为 {"巨无霸": 25.5, "新地": 12.0}。"""
    out = {}
    for raw in raw_items or []:
        name, sep, val = raw.partition("=")
        if not sep:
            raise ValueError(f"价格格式应为 名称=金额，收到：{raw}")
        name = name.strip()
        if not name:
            raise ValueError(f"缺少餐品名：{raw}")
        try:
            out[name] = float(val)
        except ValueError:
            raise ValueError(f"金额不是数字：{val}")
    return out


def weekday_cn(dt: datetime) -> str:
    """把 datetime 转成 "周一"。"""
    return "周" + "一二三四五六日"[dt.weekday()]


def cmd_record(args) -> None:
    """记录一次已确认的搭配：更新账本与口味档案。"""
    data = load(args.path)
    ledger = data["ledger"]

    try:
        prices = parse_prices(args.price)
    except ValueError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        sys.exit(1)

    entry = {
        "time": now(),
        "items": args.items or "",
        "saved": float(args.saved or 0),
        "mood": args.mood,
    }
    if prices:
        entry["prices"] = prices
    if args.paid is not None:
        entry["paid"] = float(args.paid)

    ledger["history"].append(entry)
    ledger["total_saved"] = round(ledger["total_saved"] + entry["saved"], 2)
    ledger["order_count"] += 1

    print(f"已记账：本次省 {entry['saved']:.2f} 元，"
          f"累计省 {ledger['total_saved']:.2f} 元，共 {ledger['order_count']} 单。")
    if prices:
        shown = "、".join(f"{k} {v:.2f} 元" for k, v in prices.items())
        print(f"已存价：{shown}")

    save(args.path, data)


def cmd_journal_add(args) -> None:
    data = load(args.path)
    data["journal"].append({"time": now(), "text": args.text, "mood": args.mood})
    save(args.path, data)
    print("已记下。")


def cmd_journal_clear(args) -> None:
    """清空情绪日记，保留账本与偏好。"""
    data = load(args.path)
    count = len(data["journal"])
    data["journal"] = []
    save(args.path, data)
    print(f"已清空 {count} 条记录。账本与偏好未受影响。")


def cmd_journal_show(args) -> None:
    data = load(args.path)
    items = data["journal"][-args.limit:]
    if not items:
        print("还没有记录。")
        return
    for item in items:
        mood = f"（{item['mood']}）" if item.get("mood") else ""
        print(f"{item['time']}{mood}  {item['text']}")


def cmd_stats(args) -> None:
    """输出跨次累积的战报，这是留存机制的核心。"""
    data = load(args.path)
    ledger = data["ledger"]
    journal = data["journal"]

    print("—— 麦门账本 ——")
    print(f"累计省下：{ledger['total_saved']:.2f} 元")
    print(f"确认搭配：{ledger['order_count']} 次")
    print(f"情绪记录：{len(journal)} 条")

    if journal:
        from collections import Counter
        moods = Counter(j["mood"] for j in journal if j.get("mood"))
        if moods:
            top = "、".join(m for m, _ in moods.most_common(3))
            print(f"最常出现的状态：{top}")

    if ledger["history"]:
        print(f"最近一次：{ledger['history'][-1]['time']}")


def cmd_recall(args) -> None:
    """输出「时间维度」的事实，供 G 类语录填充。

    只输出事实，不输出话术。话术由模型组合，但数字必须来自本命令——
    编造次数或价格，比不用这条语录更糟。
    """
    data = load(args.path)
    hist = data["ledger"]["history"]
    journal = data["journal"]

    if not hist and not journal:
        print("还没有任何记录。G 类（时间维度）语录暂不可用。")
        return

    # 先把历史解析成 (datetime, entry)，解析失败的丢弃
    dated = []
    for e in hist:
        try:
            dt = datetime.strptime(e.get("time", ""), "%Y-%m-%d %H:%M")
        except (ValueError, TypeError):
            continue
        dated.append((dt, e))

    print("—— 时间维度的事实 ——")

    # 1) 同类计数（受 --mood 影响）
    key = args.mood
    if key:
        n = sum(1 for e in hist if (e.get("mood") or "") == key)
        n += sum(1 for j in journal if (j.get("mood") or "") == key)
        if n >= 2:
            print(f"「{key}」已出现 {n} 次 —— 可以说「第 {n} 次」。")
        elif n == 1:
            print(f"「{key}」只出现过 1 次 —— 不可以用「第 N 次」句式。")
        else:
            print(f"「{key}」没有记录 —— 不可以用「第 N 次」句式。")
    else:
        print(f"总记录：{len(hist)} 次搭配 / {len(journal)} 条情绪")
    print()

    # 2) 星期规律（全局，与 --mood 无关）
    #    必须按「不同日期」计数：同一天记多次不算多个周
    by_wd = {}
    for dt, _ in dated:
        by_wd.setdefault(weekday_cn(dt), set()).add(dt.date())
    if by_wd:
        top_wd, top_days = max(by_wd.items(), key=lambda kv: len(kv[1]))
        n = len(top_days)
        if n >= 2:
            ds = sorted(top_days)
            consecutive = all((ds[i + 1] - ds[i]).days == 7 for i in range(n - 1))
            if consecutive:
                print(f"{top_wd}：{n} 个连续周 —— 可以说「连着 {n} 个{top_wd}了」。")
            else:
                print(f"{top_wd}：{n} 个不同的日子但不连续 —— 只能说「{n} 个{top_wd}」，不能说「连着」。")
        else:
            print(f"{top_wd}：只出现过 1 天 —— 不可以说「连着 N 个{top_wd}」。")
        print()

    # 3) 最近一次的价格变化（全局）
    if dated:
        last = dated[-1][1]
        for name, cur in (last.get("prices") or {}).items():
            prev = None
            for _, e in reversed(dated[:-1]):
                p = (e.get("prices") or {}).get(name)
                if p is not None:
                    prev = (p, e["time"])
                    break
            if prev is None:
                print(f"{name}：{cur:.2f} 元（首次记录，无对比）")
                continue
            prev_p, prev_t = prev
            diff = round(cur - prev_p, 2)
            if diff == 0:
                print(f"{name}：{cur:.2f} 元，与上次（{prev_t}）相同 —— 可以说「没变」")
            elif diff > 0:
                print(f"{name}：{cur:.2f} 元，比上次（{prev_t}）涨了 {diff:.2f} 元 —— 必须如实说涨")
            else:
                print(f"{name}：{cur:.2f} 元，比上次（{prev_t}）降了 {abs(diff):.2f} 元")
        if last.get("paid") is not None:
            print(f"最近一次实付：{last['paid']:.2f} 元")
    else:
        print("（还没有搭配记录，价格与次数都不可用）")


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="profile.py",
        description="麦门树洞本地档案模块（账本 / 偏好 / 情绪日记）",
    )
    parser.add_argument("--path", type=Path, default=DEFAULT_PATH,
                        help=f"档案文件路径，默认 {DEFAULT_PATH}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("show", help="打印完整档案").set_defaults(func=cmd_show)

    p_set = sub.add_parser("set", help="设置硬约束与偏好")
    p_set.add_argument("--allergy", action="append", help="新增过敏原，可重复")
    p_set.add_argument("--no-allergy", action="append", help="移除过敏原，可重复")
    p_set.add_argument("--religious", help="宗教或民族饮食限制；传空串清除")
    p_set.add_argument("--no-ice", dest="no_ice", action="store_true", default=None,
                       help="不吃冰")
    p_set.add_argument("--ice", dest="no_ice", action="store_false",
                       help="取消不吃冰")
    p_set.add_argument("--sugar", action="store_true", default=None, help="控糖")
    p_set.add_argument("--sodium", action="store_true", default=None, help="控钠")
    p_set.add_argument("--budget-max", type=float, dest="budget_max",
                       help="单次预算上限（元）")
    p_set.add_argument("--taste", action="append", help="口味倾向，可重复")
    p_set.add_argument("--people", type=int, help="常见用餐人数")
    p_set.add_argument("--calorie", type=int, help="单次热量目标（kcal）")
    p_set.set_defaults(func=cmd_set)

    p_fav = sub.add_parser("favorite", help="维护常点组合")
    p_fav.add_argument("--name", help="组合名称")
    p_fav.add_argument("--items", help="品项，逗号分隔")
    p_fav.add_argument("--remove", help="按名称移除")
    p_fav.set_defaults(func=cmd_favorite)

    p_rec = sub.add_parser("record", help="记录一次确认的搭配")
    p_rec.add_argument("--items", help="品项，逗号分隔")
    p_rec.add_argument("--saved", type=float, help="本次省下金额（元）")
    p_rec.add_argument("--paid", type=float, help="本次实付金额（元）")
    p_rec.add_argument("--price", action="append",
                       help="餐品成交价，格式 名称=金额；可重复，用于跨次比价")
    p_rec.add_argument("--mood", help="当时的情绪标签（仅内部记录，不向用户展示）")
    p_rec.set_defaults(func=cmd_record)

    p_ja = sub.add_parser("journal-add", help="写入一条情绪记录")
    p_ja.add_argument("text", help="用户原话")
    p_ja.add_argument("--mood", help="情绪标签")
    p_ja.set_defaults(func=cmd_journal_add)

    sub.add_parser("journal-clear", help="清空情绪日记").set_defaults(func=cmd_journal_clear)

    p_js = sub.add_parser("journal-show", help="查看情绪记录")
    p_js.add_argument("--limit", type=int, default=10, help="显示最近 N 条")
    p_js.set_defaults(func=cmd_journal_show)

    sub.add_parser("stats", help="输出累计战报").set_defaults(func=cmd_stats)

    p_rc = sub.add_parser("recall", help="查询时间维度的事实（第 N 次 / 价格没变）")
    p_rc.add_argument("--mood", help="按情绪标签筛选")
    p_rc.set_defaults(func=cmd_recall)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
