#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""不走 gh 的交互式登录，直接用设备码流程把 token 拿到手。

    python scripts/gh_login_device.py

为什么要有这个脚本：
`gh auth login --web` 在真实终端里会先让你按一次回车、再自己去轮询换 token。
这一步有两个坑：
  1. 它拿不到进度反馈，看起来就像「终端没反应」；
  2. 轮询请求一旦超时（这台机器直连 GitHub 只有约三成成功率），
     它整个流程就失败了，而浏览器那边却已经显示授权成功——
     于是你看着两边都「对」，本机却什么都没存下。

这个脚本把轮询的逻辑握在自己手里：自己发请求、自己重试、每次失败都打印
出来，并且全程走本地代理。拿到 token 后写进 gh 的配置，让它对 gh 和 git
都生效。

用一个 GitHub OAuth App 的 client id 发起设备码流程（就是 gh 自己那个
公开的 client id），不需要任何预先配置。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# gh 自己使用的公开 OAuth App client id。设备码流程不涉及 client secret。
CLIENT_ID = "01ab8ac9400c4e429b23"
SCOPES = "repo,read:org"

PROXY_CANDIDATES = [
    "http://127.0.0.1:7897",   # Clash Verge / Mihomo 默认混合端口
    "http://127.0.0.1:7890",   # Clash 旧版默认 http 端口
]


def pick_proxy() -> str | None:
    """挑一个能连上 GitHub 的本地代理。"""
    import socket

    for url in PROXY_CANDIDATES:
        host, port = "127.0.0.1", int(url.rsplit(":", 1)[1])
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.8)
        try:
            if sock.connect_ex((host, port)) == 0:
                return url
        finally:
            sock.close()
    return None


def make_opener(proxy: str | None):
    if proxy:
        handler = urllib.request.ProxyHandler({"http": proxy, "https": proxy})
    else:
        handler = urllib.request.ProxyHandler({})   # 显式不带代理
    return urllib.request.build_opener(handler)


def post_json(opener, url: str, data: dict, *, retries: int = 5) -> dict:
    """POST 并解析 JSON。直连不稳，所以失败要重试。"""
    body = urllib.parse.urlencode(data).encode()
    last_err = None
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(url, data=body, headers={
            "Accept": "application/json",
            "User-Agent": "mcd-tree-hole-login",
        })
        try:
            with opener.open(req, timeout=15) as resp:
                return json.load(resp)
        except Exception as exc:
            last_err = exc
            if attempt < retries:
                print(f"    [{attempt}/{retries}] 请求失败（{type(exc).__name__}），"
                      f"2 秒后重试……")
                time.sleep(2)
    raise RuntimeError(f"连续 {retries} 次都失败：{last_err}")


def main() -> int:
    proxy = pick_proxy()
    if proxy:
        print(f"使用代理：{proxy}")
    else:
        print("未检测到本地代理，将直连（可能不稳定）")
    opener = make_opener(proxy)

    print()
    print("第 1 步：申请设备码")
    try:
        dc = post_json(opener, "https://github.com/login/device/code", {
            "client_id": CLIENT_ID,
            "scope": SCOPES,
        })
    except Exception as exc:
        print(f"[失败] {exc}")
        return 1

    if "device_code" not in dc:
        print(f"[失败] 响应异常：{dc}")
        return 1

    user_code = dc["user_code"]
    verify_url = dc.get("verification_uri", "https://github.com/login/device")
    device_code = dc["device_code"]
    interval = max(int(dc.get("interval", 5)), 1)
    expires_in = int(dc.get("expires_in", 900))

    print()
    print("=" * 56)
    print(f"  验证码：  {user_code}")
    print(f"  打开这个：{verify_url}")
    print("=" * 56)
    print()
    print("  在浏览器里粘贴验证码、点 Authorize。")
    print("  这个窗口不用管，我会替你盯着（最多等 15 分钟）。")
    print()

    print("第 2 步：等待你完成授权")
    deadline = time.time() + expires_in
    got_token = None
    while time.time() < deadline:
        try:
            tok = post_json(opener, "https://github.com/login/oauth/access_token", {
                "client_id": CLIENT_ID,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            }, retries=2)
        except Exception as exc:
            # 单次失败不致命，继续轮询
            print(f"   轮询出错（{type(exc).__name__}），继续等……")
            time.sleep(interval)
            continue

        err = tok.get("error")
        if err == "authorization_pending":
            time.sleep(interval)
            continue
        if err == "slow_down":
            interval += 5
            time.sleep(interval)
            continue
        if err:
            print(f"[失败] GitHub 返回：{err}  {tok.get('error_description', '')}")
            return 1
        if tok.get("access_token"):
            got_token = tok["access_token"]
            break

        time.sleep(interval)

    if not got_token:
        print("[失败] 等待超时，授权没有完成。重新跑一次本脚本即可。")
        return 1

    print("   已拿到访问令牌。")

    print()
    print("第 3 步：写入 gh 配置")
    # 用 gh auth login --with-token 把令牌交给 gh，它会负责落盘。
    # --insecure-storage 存明文，绕开这台机器上出过问题的系统凭据存储。
    try:
        proc = subprocess.run(
            ["gh", "auth", "login", "--hostname", "github.com",
             "--with-token", "--insecure-storage"],
            input=got_token + "\n",
            text=True, capture_output=True, timeout=60,
        )
    except FileNotFoundError:
        print("[失败] 找不到 gh 命令。")
        return 1

    if proc.returncode != 0:
        print("[失败] 写入配置时出错：")
        print("  " + (proc.stderr or proc.stdout).strip())
        return 1
    print("   已写入。")

    print()
    print("第 4 步：确认可用")
    check = subprocess.run(
        ["gh", "api", "user", "--jq", ".login"],
        text=True, capture_output=True,
    )
    who = (check.stdout or "").strip()
    if check.returncode != 0 or not who:
        print("[失败] 接口仍不可用：")
        print("  " + (check.stderr or "").strip())
        return 1
    print(f"   [通过] 已确认身份：{who}")

    # 让 git 也复用这份凭据（推送时不再弹认证窗口）
    subprocess.run(["gh", "auth", "setup-git"], capture_output=True)

    print()
    print("=" * 56)
    print("  登录完成。接下来运行：")
    print("      python scripts/publish_to_github.py")
    print("=" * 56)
    return 0


if __name__ == "__main__":
    sys.exit(main())
