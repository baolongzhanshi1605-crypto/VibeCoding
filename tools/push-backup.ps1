<#
.SYNOPSIS
  把 dsh-api-balance 子项目单独备份到 GitHub（VibeCoding 仓库的一个独立分支）。

.DESCRIPTION
  设计要点（都是为了「不弄脏别的项目」）：
    * 只推送**本子项目**：用 git 底层命令把 dsh-api-balance/ 抽成一条独立历史，
      仓库里其它子项目（chaoxing-homework-reminder 等）与根文件都不会被带上。
    * 只写**新分支**：远程 refspec 锁定为 refs/heads/<Branch>，远程 main 原样不动。
    * **绝不强推**：脚本里没有任何 --force / +refspec，非快进会被 git 直接拒绝。
    * 推之前会做守卫检查：目标分支名不能是 main/master；仓库工作区必须干净。

  ⚠️ 环境说明：本机 git 未配置代理，如果 github.com 连不上会直接报连接失败。
  请先确认你的代理（v2rayN 等）已开启，必要时给 git 配上：
      git config --global http.proxy  http://127.0.0.1:10809
      git config --global https.proxy http://127.0.0.1:10809
  （端口以你的代理实际监听为准；用完可用 --unset 取消。）

.PARAMETER Remote
  远程名，默认 vibecoding（首次运行会自动添加）。

.PARAMETER Branch
  远程分支名，默认 dsh-api-balance。不允许是 main / master。

.PARAMETER WhatIf
  只演练：重建本地分支并打印将要推送的内容，不联网。

.EXAMPLE
  pwsh -File tools\push-backup.ps1
  pwsh -File tools\push-backup.ps1 -WhatIf
#>
[CmdletBinding()]
param(
  [string]$Remote = 'vibecoding',
  [string]$Branch = 'dsh-api-balance',
  [string]$RemoteUrl = 'https://github.com/baolongzhanshi1605-crypto/VibeCoding.git',
  [switch]$WhatIf
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot                  # …\repo-one\dsh-api-balance
$RepoRoot = (Resolve-Path (Join-Path $ProjectRoot '..')).Path    # …\repo-one（往上一级）
$SubProjectName = Split-Path -Leaf $ProjectRoot

function Say([string]$m, [string]$c = 'Gray') { Write-Host $m -ForegroundColor $c }
function Step([string]$m) { Write-Host "  · $m" }

# ---- 守卫 1：目标分支不许是 main/master ------------------------------------
if ($Branch -in @('main', 'master', 'HEAD')) {
  throw "拒绝执行：目标分支 '$Branch' 是主干分支名。本脚本只允许推送到独立分支。"
}
if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot '.git'))) {
  throw "找不到仓库：$RepoRoot 不是 git 仓库根。"
}

Say ""
Say "dsh-api-balance · 备份推送到 GitHub" 'Cyan'
Say "  仓库根   : $RepoRoot"
Say "  子项目   : $SubProjectName"
Say "  远程     : $Remote  ($RemoteUrl)"
Say "  目标分支 : $Branch"
Say ""

# ---- 守卫 2：工作区必须干净（本子项目不能有未提交改动）--------------------
Push-Location $RepoRoot
try {
  $status = git status --short
  if ($status) {
    Say "工作区不干净，请先提交再备份：" 'Yellow'
    $status | ForEach-Object { Write-Host "    $_" }
    throw '工作区有未提交改动。'
  }
  Step '工作区干净'

  # ---- 重建「只含本子项目」的独立分支（等效 git subtree split，但不依赖 sh.exe）----
  $tree = (git rev-parse "HEAD:$SubProjectName").Trim()
  if (-not $tree) { throw "HEAD 里找不到子项目目录 $SubProjectName —— 请先 git add + git commit。" }
  Step "子树 tree 对象：$tree"

  $stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
  $message = "$SubProjectName 备份 @ $stamp"
  $commit = (git commit-tree $tree -m $message).Trim()
  git update-ref "refs/heads/$Branch" $commit
  Step "本地分支 refs/heads/$Branch → $commit"

  $files = git ls-tree -r --name-only "refs/heads/$Branch"
  Say ""
  Say "  该分支将包含以下文件（子项目内容位于仓库根，不带父目录）：" 'DarkGray'
  $files | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
  Say ""

  # ---- 幂等配置远程 ---------------------------------------------------------
  $existing = git remote
  if ($existing -notcontains $Remote) {
    if ($WhatIf) { Step "会添加远程 $Remote → $RemoteUrl" }
    else { git remote add $Remote $RemoteUrl; Step "已添加远程 $Remote → $RemoteUrl" }
  } else {
    Step "远程 $Remote 已存在"
  }

  if ($WhatIf) {
    Say "WhatIf：不联网。实际执行时会是：" 'Yellow'
    Say "  git push $Remote refs/heads/$Branch`:refs/heads/$Branch" 'DarkGray'
    return
  }

  # ---- 推送（显式 refspec，只创建目标分支）--------------------------------
  Say "推送中…" 'Cyan'
  git push $Remote "refs/heads/$Branch`:refs/heads/$Branch"
  if ($LASTEXITCODE -ne 0) { throw "推送失败（退出码 $LASTEXITCODE）。多半是网络/代理或 GitHub 登录问题，见文件头说明。" }

  Say ""
  Say "备份完成。" 'Green'
  Say ""
  Say "恢复/回档命令（把远端那份取回来对照或还原）：" 'Cyan'
  Say "  git fetch $Remote" 'Gray'
  Say "  git diff refs/remotes/$Remote/$Branch -- $SubProjectName        # 看差异" 'Gray'
  Say "  git checkout refs/remotes/$Remote/$Branch -- $SubProjectName   # 整目录还原" 'Gray'
  Say ""
  Say "本地回档点（更快，不需要网络）：" 'Cyan'
  Say "  git tag -l 'dsh-api-balance-*'                     # 列出标签" 'Gray'
  Say "  git restore --source=dsh-api-balance-v0.3.0 -- $SubProjectName   # 还原到某个标签" 'Gray'
  Say ""
}
finally { Pop-Location }
