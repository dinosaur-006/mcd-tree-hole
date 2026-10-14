# 登录 GitHub 并发布本项目。一条命令跑完，只需要你在浏览器点一次「授权」。
#
#     powershell -ExecutionPolicy Bypass -File scripts\login_and_publish.ps1
#
# 为什么要写成脚本：gh auth login 是交互式的，中间会问你三个问题。这个脚本
# 把答案都预填好了，你只需要完成最后一件事——在浏览器里点授权。
#
# 注意：本文件必须存成「UTF-8 带 BOM」。Windows PowerShell 5.1 读 .ps1 时
# 默认按系统 ANSI（中文机器上是 GBK）解码，没有 BOM 的话中文会整片乱码。

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "=== 第 0 步：网络自检 ===" -ForegroundColor Cyan
# GitHub 直连时通时不通，先测一下，省得登录到一半卡住还不知道为什么。
#
# 为什么不用 Test-NetConnection：它在 Windows PowerShell 5.1 上行为不稳，
# 实测会卡住或者返回空值，反而把本来通畅的网络误判成不通。这里直接用
# .NET 的 TcpClient，不依赖任何模块，5.1 和 7 上都能跑，还带 5 秒超时。
function Test-PortOpen {
    param([string]$Host_, [int]$Port, [int]$TimeoutMs = 5000)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect($Host_, $Port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne($TimeoutMs, $false)) {
            return $false   # 超时
        }
        $client.EndConnect($async)   # 连不上会在这里抛异常
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

if (Test-PortOpen -Host_ "github.com" -Port 443) {
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
Write-Host "  在浏览器里粘贴验证码，然后点 Authorize 就行了。" -ForegroundColor Gray
Write-Host ""
Write-Host "  如果浏览器没自动打开，手动访问：https://github.com/login/device" -ForegroundColor Gray
Write-Host ""

# 这里把所有交互点都用参数消掉了，不需要往标准输入里喂答案——
# 实测「--web --git-protocol https --scopes ...」这一组合下，gh 一个问题都不问，
# 直接打印验证码并打开浏览器。用管道喂答案反而容易让 gh 读错。
#   --web             走设备码流程，浏览器里点授权，不碰任何 token
#   --git-protocol    预先定好 HTTPS，免得它反问；同时让 git 复用这份凭据
#   --scopes          发布需要 repo（读写仓库）和 read:org
gh auth login -h github.com --web --git-protocol https --scopes "repo,read:org"

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "[失败] 登录没有完成。常见原因：" -ForegroundColor Red
    Write-Host "  1. 浏览器里没点授权，或者点了拒绝" -ForegroundColor Red
    Write-Host "  2. 中途断网了，重跑一次本脚本即可" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "=== 第 2 步：确认登录状态 ===" -ForegroundColor Cyan
gh auth status

Write-Host ""
Write-Host "=== 第 3 步：发布（建仓 + 推送 + 校验）===" -ForegroundColor Cyan
# 切到项目根目录，这样 python 脚本里的相对路径才对
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
