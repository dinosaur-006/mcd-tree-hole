#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把本项目发布到 GitHub：建仓（若不存在）+ 关联远程 + 推送 + 校验。

     python scripts/publish_to_github.py --check   # 只体检，什么都不改
     python scripts/publish_to_github.py           # 真正发布

为什么要有这个脚本：发布不是"敲一条 git push"那么简单——要确认分支名、
确认没有未提交的改动（否则线上和你本地看到的不一样）、确认仓库还没建、
确认推上去之后真的可见。这些步骤每次都靠人记，迟早会漏一步。

前置条件只有一个：`gh` 已登录（gh auth login -h github.com）。
脚本会自己检查，没登录就停下来告诉你该敲什么，不会瞎推。
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

OWNER = "dinosaur-006"
REPO = "mcd-tree-hole"
FULL = f"{OWNER}/{REPO}"

DESCRIPTION = "说一句，我给你点一份。基于麦当劳 MCP 的对话式点餐 Skill。"
TOPICS = ["mcp", "mcdonalds", "workbuddy", "skill", "agent"]

ROOT = Path(__file__).resolve().parent.parent


class Fail(Exception):
    """体检不通过。消息会原样打给用户，所以要说人话。"""


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=check,
    )


def ok(msg: str) -> None:
    print(f"  [通过] {msg}")


def info(msg: str) -> None:
    print(f"  [信息] {msg}")


# ----------------------------------------------------------------------
# 体检
# ----------------------------------------------------------------------

def check_is_repo() -> None:
    if not (ROOT / ".git").exists():
        raise Fail(f"{ROOT} 不是一个 git 仓库。")
    ok("在 git 仓库根目录")


def check_clean() -> None:
    dirty = run(["git", "status", "--porcelain"]).stdout.strip()
    if dirty:
        raise Fail(
            "有未提交的改动，先提交再发布——"
            "否则 GitHub 上看到的和你本地不是同一份东西：\n"
            + "\n".join("      " + line for line in dirty.splitlines()[:10])
        )
    ok("工作区干净（没有未提交的改动）")


def check_branch() -> str:
    branch = run(["git", "branch", "--show-current"]).stdout.strip()
    if not branch:
        raise Fail("当前处于游离 HEAD 状态，请先切到一个分支。")
    if branch != "main":
        info(f"当前分支是 {branch}（不是 main），将推送这个分支")
    else:
        ok("当前分支 main")
    return branch


def check_gh() -> None:
    if shutil.which("gh") is None:
        raise Fail(
            "没找到 gh（GitHub CLI）。\n"
            "  安装：winget install --id GitHub.cli\n"
            "  或者改用网页建仓 + git push 的老办法（见 README）。"
        )

    status = run(["gh", "auth", "status"], check=False)
    if status.returncode != 0:
        raise Fail(
            "gh 没有登录（这台机器上的凭据已失效）。这一步只能由你本人完成，\n"
            "  因为它需要你在浏览器里点一次授权：\n\n"
            "      gh auth login -h github.com\n\n"
            "  登录后重新运行本脚本即可，剩下的会自动做完。"
        )
    ok("gh 已登录")


# ----------------------------------------------------------------------
# 发布
# ----------------------------------------------------------------------

def repo_exists() -> bool:
    return run(["gh", "repo", "view", FULL], check=False).returncode == 0


def create_repo() -> None:
    if repo_exists():
        info(f"仓库 {FULL} 已存在，跳过创建")
        return
    print(f"  -> 创建公开仓库 {FULL}")
    run([
        "gh", "repo", "create", FULL,
        "--public",
        "--description", DESCRIPTION,
    ])
    ok("仓库已创建")


def share_credentials_with_git() -> None:
    """让 git 复用 gh 的登录状态。

    gh 的登录和 git 的凭据助手是两套东西：gh 登录了，不代表 `git push`
    能拿到凭据——它可能弹一个认证窗口，在自动化里就会卡死。这一步在
    两者之间搭个桥。
    """
    result = run(["gh", "auth", "setup-git"], check=False)
    if result.returncode == 0:
        ok("git 已复用 gh 的凭据（推送不会弹认证窗口）")
    else:
        info("gh auth setup-git 没成功，推送时可能需要你手动认证一次")


def ensure_remote() -> None:
    current = run(["git", "remote", "get-url", "origin"], check=False)
    want = f"https://github.com/{FULL}.git"
    if current.returncode != 0:
        run(["git", "remote", "add", "origin", want])
        ok(f"已关联 origin -> {want}")
    elif current.stdout.strip() != want:
        raise Fail(
            f"origin 指向的是 {current.stdout.strip()}，不是 {want}。\n"
            "  请先确认这是不是你要推的仓库，再手动处理。"
        )
    else:
        ok("origin 已正确指向目标仓库")


def push(branch: str) -> None:
    ahead = run(["git", "rev-list", "--count", f"origin/{branch}..{branch}"],
                check=False)
    if ahead.returncode == 0 and ahead.stdout.strip() == "0":
        info("远端已经是最新的，没有新提交要推")
    print(f"  -> 推送 {branch}")
    run(["git", "push", "-u", "origin", branch])
    ok(f"{branch} 已推送")


def add_topics() -> None:
    run(["gh", "repo", "edit", FULL, "--add-topic", ",".join(TOPICS)],
        check=False)
    ok("已设置仓库话题：" + "、".join(TOPICS))


def verify(branch: str) -> None:
    """真去看一眼远端：本地 HEAD 和远端分支必须是同一个提交。"""
    local = run(["git", "rev-parse", "HEAD"]).stdout.strip()
    remote = run(["git", "rev-parse", f"origin/{branch}"], check=False)

    view = run(["gh", "repo", "view", FULL,
                "--json", "url,visibility,defaultBranchRef"])
    print()
    print("  远端状态：")
    print("    " + view.stdout.strip().replace("\n", "\n    "))

    if remote.returncode != 0:
        raise Fail(f"远端读不到 origin/{branch}，推送可能没有生效。")
    if remote.stdout.strip() != local:
        raise Fail(
            f"远端 {branch} 的提交是 {remote.stdout.strip()[:8]}，"
            f"本地是 {local[:8]}，两者不一致。"
        )
    print()
    ok(f"校验通过：远端 {branch} 与本地 HEAD 一致（{local[:8]}）")


# ----------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="发布本项目到 GitHub（建仓 + 推送 + 校验）")
    parser.add_argument("--check", action="store_true",
                        help="只做体检，不改动任何东西")
    args = parser.parse_args()

    print(f"项目目录：{ROOT}")
    print(f"目标仓库：{FULL}")
    print()
    print("体检：")

    try:
        check_is_repo()
        check_clean()
        branch = check_branch()
        check_gh()
    except Fail as exc:
        print()
        print("[停在这里] " + str(exc))
        return 1

    if args.check:
        print()
        print("体检全部通过，可以发布。去掉 --check 即可执行：")
        print("    python scripts/publish_to_github.py")
        return 0

    print()
    print("开始发布：")
    try:
        create_repo()
        share_credentials_with_git()
        ensure_remote()
        push(branch)
        add_topics()
        verify(branch)
    except subprocess.CalledProcessError as exc:
        print()
        print(f"[失败] 命令返回非零：{' '.join(exc.cmd)}")
        if exc.stderr:
            print("  " + exc.stderr.strip())
        return 1
    except Fail as exc:
        print()
        print("[停在这里] " + str(exc))
        return 1

    print()
    print(f"完成。仓库地址：https://github.com/{FULL}")
    print()
    print("还差两步（只能在网页上做）：")
    print("  1. Settings -> Social preview，上传 assets/social-preview.png")
    print("  2. 确认 About 里的 Description 与 Topics 已生效")
    return 0


if __name__ == "__main__":
    sys.exit(main())
