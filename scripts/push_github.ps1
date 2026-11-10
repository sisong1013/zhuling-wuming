# 一键把 game/ 推到 GitHub（Railway 用）
#
# 用法（三种任选）：
#   1) 已经 gh auth login 过：
#        powershell -ExecutionPolicy Bypass -File scripts\push_github.ps1
#   2) 用个人访问令牌（PAT，classic 勾 repo / fine-grained 勾 Contents:write）：
#        $env:GITHUB_TOKEN="ghp_xxx"; powershell -ExecutionPolicy Bypass -File scripts\push_github.ps1
#   3) 已有空仓库地址：
#        powershell -ExecutionPolicy Bypass -File scripts\push_github.ps1 -Remote https://github.com/你/仓库.git
#
# 参数：
#   -RepoName   仓库名（默认 zhuling-wuming）
#   -Private    建私有仓库（默认公开）
#   -Remote     直接指定远端，跳过 gh 建仓

param(
  [string]$RepoName = "zhuling-wuming",
  [switch]$Private,
  [string]$Remote = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# gh 可能刚装好，PATH 里还没有
$ghCandidates = @(
  "C:\Program Files\GitHub CLI\gh.exe",
  (Join-Path $env:LOCALAPPDATA "Programs\GitHub CLI\gh.exe")
)
$gh = (Get-Command gh -ErrorAction SilentlyContinue).Source
if (-not $gh) { $gh = $ghCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1 }

if (-not (Test-Path ".git")) {
  git init -q
}

# 提交者身份（只写本仓库，不动全局）
git config user.name  "stage-bot"
git config user.email "bot@local"
git branch -M main 2>$null

if ($env:GITHUB_TOKEN) {
  $env:GH_TOKEN = $env:GITHUB_TOKEN
  Write-Host "使用 GITHUB_TOKEN 认证" -ForegroundColor Cyan
}

git add -A
$pending = git status --porcelain
if ($pending) {
  git commit -q -m "chore: 同步最新代码"
  if ($LASTEXITCODE -ne 0) { Write-Host "没有新改动需要提交" -ForegroundColor DarkGray }
} else {
  Write-Host "工作区干净，跳过提交" -ForegroundColor DarkGray
}

if (-not $Remote) {
  if (-not $gh) { throw '找不到 gh。请先安装：winget install --id GitHub.cli -e' }
  & $gh auth status *> $null
  if ($LASTEXITCODE -ne 0) {
    throw ' gh 未登录 。 先运行 gh auth login ，或先设置环境变量 GITHUB_TOKEN 再重试 '
  }
  $visibility = if ($Private) { "--private" } else { "--public" }
  Write-Host "创建仓库 $RepoName 并推送…" -ForegroundColor Cyan
  & $gh repo create $RepoName $visibility --source . --remote origin --push
  if ($LASTEXITCODE -ne 0) { throw "gh repo create 失败（仓库名可能被占用，换 -RepoName）" }
} else {
  git remote remove origin 2>$null
  git remote add origin $Remote
  git push -u origin main --force
  if ($LASTEXITCODE -ne 0) { throw "git push 失败：检查远端地址与权限" }
}

git remote -v
Write-Host ""
Write-Host "推送完成。下一步在 Railway：New Project -> Deploy from GitHub repo -> 选这个仓库" -ForegroundColor Green
Write-Host "然后在 Variables 里加 LLM_API_KEY；Settings -> Networking -> Generate Domain" -ForegroundColor Green
