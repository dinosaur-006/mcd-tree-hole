# 登录 GitHub 并发布本项目。一条命令跑完，只需要你在浏览器点一次「授权」。
#
#     powershell -ExecutionPolicy Bypass -File scripts\login_and_publish.ps1
#
# 为什么要写成脚本：gh auth login 是交互式的，中间会问你三个问题。这个脚本
# 把答案都预填好了，你只需要完成最后一件事——在浏览器里点授权。

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "=== 第 0 步：网络自检 ===" -ForegroundColor Cyan
# GitHub 直连时通时不通，先测一下，省得登录到一半卡住还不知道为什么。
$probe = Test-NetConnection -ComputerName github.com -Port 443 -WarningAction SilentlyContinue `
    -InformationLevel Quiet
if ($probe) {
    Write-Host "  [通过] 能连上 github.com:443" -ForegroundColor Green
} else {
    Write-Host "  [警告] 连不上 github.com:443。" -ForegroundColor Yellow
    Write-Host "         请先确认梯子开着（Clash 要开 TUN 模式，或者系统代理要生效），" -ForegroundColor Yellow
    Write-Host "         然后重新运行本脚本。" -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "=== 第 1 步：登录 GitHub ===" -ForegroundColor Cyan
Write-Host "  接下来会显示一个 8 位验证码，并把浏览器打开。" -ForegroundColor Gray
Write-Host "  在浏览器里粘贴验证码 -> 点 Authorize 就行了。" -ForegroundColor Gray
Write-Host ""
Write-Host "  如果浏览器没自动打开，手动访问：https://github.com/login/device" -ForegroundColor Gray
Write-Host ""

# 三个问题一次性预填：HTTPS 协议 / 让 git 复用凭据 / 用浏览器登录。
# --web 让 gh 走设备码流程，不需要粘贴任何 token。
"HTTPS`nY`n" | gh auth login -h github.com --web --scopes "repo,read:org"

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "[失败] 登录没有完成。常见原因：" -ForegroundColor Red
    Write-Host "  1. 浏览器里没点授权，或者点了拒绝" -ForegroundColor Red
    Write-Host "  2. 中途断网了——重跑一次本脚本即可" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "=== 第 2 步：确认登录状态 ===" -ForegroundColor Cyan
gh auth status

Write-Host ""
Write-Host "=== 第 3 步：发布（建仓 + 推送 + 校验）===" -ForegroundColor Cyan
# 换成项目根目录，这样 python 脚本里的相对路径才对
Push-Location (Split-Path -Parent $PSScriptRoot)
try {
    python scripts/publish_to_github.py
    $code = $LASTEXITCODE
} finally {
    Pop-Location
}

if ($code -ne 0) {
    Write-Host ""
    Write-Host "[停在这里] 发布没有跑完，看上面对应的提示。" -ForegroundColor Red
    exit $code
}

Write-Host ""
Write-Host "=== 全部完成 ===" -ForegroundColor Green
Write-Host "仓库地址：https://github.com/dinosaur-006/mcd-tree-hole" -ForegroundColor Green
