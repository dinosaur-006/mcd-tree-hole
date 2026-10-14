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
# 为什么不用 Test-NetConnection：它在旧版 Windows 上行为不稳，实测会卡住
# 或者返回空值，反而把本来通畅的网络误判成不通。这里直接用 .NET 的
# TcpClient，不依赖任何模块，还自带超时。
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

# 本地代理探测。
# 这台机器上检测到：github.com 直连的稳定性只有约三成（6 次里 2 次通），
# 而 gh 登录要在几秒内连续完成「取设备码 → 轮询换 token」好几次请求，
# 这种时通时不通的网络下几乎必然失败——表现就是浏览器里明明点了授权
# 显示成功，本机 gh 却什么都没存下。
# 走本地代理则 6/6 全通（约 0.8s）。所以这里自动探测并启用它。
$proxyCandidates = @(
    @{ Host_ = "127.0.0.1"; Port = 7897 },   # Clash Verge / Mihomo 默认混合端口
    @{ Host_ = "127.0.0.1"; Port = 7890 }    # Clash 旧版默认 http 端口
)
$proxyUrl = $null
foreach ($c in $proxyCandidates) {
    if (Test-PortOpen -Host_ $c.Host_ -Port $c.Port -TimeoutMs 800) {
        $proxyUrl = "http://$($c.Host_):$($c.Port)"
        break
    }
}

if ($proxyUrl) {
    Write-Host "  [通过] 检测到本地代理 $proxyUrl，本次全程走它" -ForegroundColor Green
    # 只影响本脚本这一次运行，不改系统设置；退出终端即失效。
    $env:HTTP_PROXY  = $proxyUrl
    $env:HTTPS_PROXY = $proxyUrl
    # 让 git 也走同一个代理（只针对 github.com，不碰其他站点的访问）
    git config --global http.https://github.com.proxy $proxyUrl | Out-Null
} else {
    Write-Host "  [提示] 没检测到本地代理，改用直连" -ForegroundColor Gray
    Write-Host "         若稍后登录失败，多半是直连不稳：把梯子开起来再跑一次。" -ForegroundColor Gray
}

if (-not (Test-PortOpen -Host_ "github.com" -Port 443)) {
    Write-Host "  [警告] 连不上 github.com:443。" -ForegroundColor Yellow
    Write-Host "         请先确认梯子开着（Clash 开 TUN 模式，或让系统代理生效），" -ForegroundColor Yellow
    Write-Host "         然后重新运行本脚本。" -ForegroundColor Yellow
    exit 1
}
Write-Host "  [通过] github.com:443 可连通" -ForegroundColor Green

Write-Host ""
Write-Host "=== 第 1 步：清掉本机可能残留的旧凭据 ===" -ForegroundColor Cyan
# 这台机器上曾经登录过，但凭据已经失效了。gh 在 Windows 上把 token 交给
# 系统凭据存储管，而它读的时候会优先取旧的那一条——于是「重新登录成功」
# 也可能仍然被判 invalid（实测就是这样：浏览器里明明授权成功了，gh api
# 却依然回 401）。所以先把旧的清掉，再谈重新登录。
# 这一步只删本机配置，不会去远端撤销 token，是安全的。
$stale = cmdkey /list | Select-String "gh:github.com"
if ($stale) {
    Write-Host "  发现残留凭据，正在清除……" -ForegroundColor Gray
    cmdkey /delete:"LegacyGeneric:target=gh:github.com:dinosaur-006" 2>&1 | Out-Null
    cmdkey /delete:"LegacyGeneric:target=gh:github.com:" 2>&1 | Out-Null
    gh auth logout -h github.com -u dinosaur-006 2>&1 | Out-Null
    Write-Host "  [完成] 旧凭据已清除" -ForegroundColor Green
} else {
    Write-Host "  [跳过] 没有发现残留凭据" -ForegroundColor Gray
}

Write-Host ""
Write-Host "=== 第 2 步：登录 GitHub ===" -ForegroundColor Cyan
Write-Host "  接下来会显示一个 8 位验证码，并把浏览器打开。" -ForegroundColor Gray
Write-Host "  在浏览器里粘贴验证码，然后点 Authorize 就行了。" -ForegroundColor Gray
Write-Host ""
Write-Host "  如果浏览器没自动打开，手动访问：https://github.com/login/device" -ForegroundColor Gray
Write-Host ""

# 这里把所有交互点都用参数消掉了，不需要往标准输入里喂答案——
# 实测「--web --git-protocol https --scopes ...」这一组合下，gh 一个问题都不问，
# 直接打印验证码并打开浏览器。用管道喂答案反而容易让 gh 读错。
#   --web              走设备码流程，浏览器里点授权，不碰任何 token
#   --git-protocol     预先定好 HTTPS，免得它反问；同时让 git 复用这份凭据
#   --scopes           发布需要 repo（读写仓库）和 read:org
#   --insecure-storage 把 token 存成明文文件，绕开系统凭据存储。
#                      这台机器的凭据存储有过「存进去读不出来」的记录，
#                      明文存储反而稳。文件在你自己的用户目录下，且绝不入库。
gh auth login -h github.com --web --git-protocol https --insecure-storage --scopes "repo,read:org"

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "[失败] 登录没有完成。常见原因：" -ForegroundColor Red
    Write-Host "  1. 浏览器里没点授权，或者点了拒绝" -ForegroundColor Red
    Write-Host "  2. 中途断网了，重跑一次本脚本即可" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "=== 第 3 步：确认登录真的可用 ===" -ForegroundColor Cyan
# 只看 gh auth status 不够——它可能报成功，实际 API 仍然 401。
# 这里真去打一次接口，拿到用户名才算数。
gh auth status
Write-Host ""
$who = gh api user --jq ".login" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "[失败] 登录状态看着没问题，但接口返回 401，凭据其实不可用。" -ForegroundColor Red
    Write-Host "  请再跑一次本脚本（第 1 步会清掉这次留下的凭据再重来）。" -ForegroundColor Red
    exit 1
}
Write-Host "  [通过] 已确认身份：$who" -ForegroundColor Green

Write-Host ""
Write-Host "=== 第 4 步：发布（建仓 + 推送 + 校验）===" -ForegroundColor Cyan
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
