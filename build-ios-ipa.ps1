[CmdletBinding()]
param(
    [string]$CommitMessage = "Build iOS IPA",
    [string]$ArtifactDirectory = ".\artifacts\ios",
    [ValidateRange(5, 180)]
    [int]$TimeoutMinutes = 45,
    [switch]$RunEvenIfClean,
    [switch]$KeepPreviousArtifact
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-External {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(Mandatory = $false)]
        [string[]]$Arguments = @()
    )

    $output = (& $FilePath @Arguments 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath failed with exit code $LASTEXITCODE. $output"
    }
    if ([string]::IsNullOrWhiteSpace($output)) {
        return
    }
    return $output
}

function Invoke-Git {
    param([string[]]$Arguments)
    return Invoke-External -FilePath "git" -Arguments $Arguments
}

function Invoke-Gh {
    param([string[]]$Arguments)
    return Invoke-External -FilePath "gh" -Arguments $Arguments
}

function Get-JsonFromGh {
    param([string[]]$Arguments)
    $text = Invoke-Gh -Arguments $Arguments
    if ([string]::IsNullOrWhiteSpace($text)) {
        return $null
    }
    return $text | ConvertFrom-Json
}

function Set-PipelineProgress {
    param(
        [int]$Percent,
        [string]$Status
    )
    Write-Progress -Id 1 -Activity "Ezcan iOS IPA pipeline" -Status $Status -PercentComplete $Percent
}

function Show-CompletionAlert {
    param(
        [string]$Title,
        [string]$Message,
        [bool]$Success
    )

    try {
        Add-Type -AssemblyName PresentationFramework
        $icon = if ($Success) {
            [System.Windows.MessageBoxImage]::Information
        } else {
            [System.Windows.MessageBoxImage]::Error
        }
        [System.Windows.MessageBox]::Show(
            $Message,
            $Title,
            [System.Windows.MessageBoxButton]::OK,
            $icon
        ) | Out-Null
    } catch {
        [Console]::Beep(900, 250)
        Write-Host "$Title`n$Message"
    }
}

function Assert-Prerequisites {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "Git was not found on PATH. Install Git for Windows first."
    }
    if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
        throw "GitHub CLI (gh) was not found on PATH. Install it from https://cli.github.com/ first."
    }

    $branch = (Invoke-Git -Arguments @("branch", "--show-current")).Trim()
    if ($branch -ne "main") {
        throw "This script only pushes main. Current branch is '$branch'."
    }

    [void](Invoke-Gh -Arguments @("auth", "status"))
}

function Assert-NoSensitivePaths {
    $statusLines = @(Invoke-Git -Arguments @("status", "--porcelain"))
    $blockedPattern = '(?i)(^|[\\/])([^\\/]*(password|secret|token|credential)[^\\/]*|[^\\/]+\.(p12|mobileprovision|pem|key|env))$'
    foreach ($line in $statusLines) {
        if ($line -match '^..\s+(.+)$') {
            $changedPath = $Matches[1]
            if ($changedPath -match $blockedPattern) {
                throw "Refusing to stage a possibly sensitive path: $changedPath"
            }
        }
    }
}

function Get-WorkflowRun {
    param(
        [string]$HeadSha,
        [datetime]$NotBefore,
        [switch]$ManualRun
    )

    $runs = @(Get-JsonFromGh -Arguments @(
            "run", "list", "--workflow", "build-ios.yml", "--branch", "main", "--limit", "20",
            "--json", "databaseId,status,conclusion,headSha,event,createdAt,url"
        ))
    foreach ($run in $runs) {
        if ($run.headSha -ne $HeadSha) { continue }
        if ($ManualRun -and $run.event -ne "workflow_dispatch") { continue }
        if ([datetime]$run.createdAt -lt $NotBefore.ToUniversalTime()) { continue }
        return $run
    }
    return $null
}

function Wait-ForWorkflowRun {
    param(
        [string]$HeadSha,
        [datetime]$NotBefore,
        [switch]$ManualRun
    )

    $searchDeadline = (Get-Date).AddMinutes(3)
    do {
        $run = Get-WorkflowRun -HeadSha $HeadSha -NotBefore $NotBefore -ManualRun:$ManualRun
        if ($null -ne $run) { return $run }
        Set-PipelineProgress -Percent 32 -Status "Waiting for GitHub Actions to create the build run..."
        Start-Sleep -Seconds 5
    } while ((Get-Date) -lt $searchDeadline)

    throw "GitHub Actions did not create a build-ios run for commit $HeadSha."
}

function Wait-ForWorkflowCompletion {
    param(
        [Parameter(Mandatory = $true)]
        $Run
    )

    $deadline = (Get-Date).AddMinutes($TimeoutMinutes)
    do {
        $current = Get-JsonFromGh -Arguments @(
            "run", "view", "$($Run.databaseId)",
            "--json", "databaseId,status,conclusion,url"
        )
        $status = [string]$current.status
        if ($status -eq "completed") {
            if ([string]$current.conclusion -ne "success") {
                throw "GitHub Actions failed with conclusion '$($current.conclusion)'. Run: $($current.url)"
            }
            Set-PipelineProgress -Percent 90 -Status "GitHub Actions succeeded. Downloading the IPA artifact..."
            return $current
        }

        $elapsed = [math]::Max(0, ($TimeoutMinutes * 60) - ($deadline - (Get-Date)).TotalSeconds)
        $percent = [math]::Min(88, [int](38 + ($elapsed / ($TimeoutMinutes * 60) * 48)))
        Set-PipelineProgress -Percent $percent -Status "iOS build is $status..."
        Start-Sleep -Seconds 10
    } while ((Get-Date) -lt $deadline)

    throw "The iOS build exceeded the $TimeoutMinutes minute timeout. Run: $($Run.url)"
}

try {
    Set-PipelineProgress -Percent 2 -Status "Checking Git and GitHub CLI prerequisites..."
    Assert-Prerequisites
    Assert-NoSensitivePaths

    $beforeStatus = @(Invoke-Git -Arguments @("status", "--porcelain"))
    $hasChanges = $beforeStatus.Count -gt 0
    $manualRun = $false
    $pushSha = $null

    if ($hasChanges) {
        Set-PipelineProgress -Percent 10 -Status "Staging repository changes..."
        [void](Invoke-Git -Arguments @("add", "--all"))
        & git diff --cached --quiet
        $stagedExitCode = $LASTEXITCODE
        if ($stagedExitCode -eq 0) {
            throw "The worktree reported changes, but nothing was staged. Check ignored files."
        }

        Set-PipelineProgress -Percent 18 -Status "Creating commit '$CommitMessage'..."
        [void](Invoke-Git -Arguments @("commit", "-m", $CommitMessage))
        $pushSha = (Invoke-Git -Arguments @("rev-parse", "HEAD")).Trim()

        Set-PipelineProgress -Percent 26 -Status "Pushing $pushSha to origin/main..."
        [void](Invoke-Git -Arguments @("push", "origin", "main"))
    } elseif (-not $RunEvenIfClean) {
        throw "There are no changes to commit. Make changes first, or run with -RunEvenIfClean to build current main."
    } else {
        $pushSha = (Invoke-Git -Arguments @("rev-parse", "HEAD")).Trim()
        $manualRun = $true
        Set-PipelineProgress -Percent 26 -Status "Worktree is clean. Starting a manual build for $pushSha..."
        $runRequestedAt = Get-Date
        [void](Invoke-Gh -Arguments @("workflow", "run", "build-ios.yml", "--ref", "main"))
    }

    if (-not $manualRun) {
        $runRequestedAt = (Get-Date).AddMinutes(-1)
    }
    $run = Wait-ForWorkflowRun -HeadSha $pushSha -NotBefore $runRequestedAt -ManualRun:$manualRun
    Set-PipelineProgress -Percent 38 -Status "Tracking GitHub Actions run $($run.databaseId)..."
    $completedRun = Wait-ForWorkflowCompletion -Run $run

    $resolvedArtifactDirectory = [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $ArtifactDirectory))
    if (-not $KeepPreviousArtifact -and (Test-Path $resolvedArtifactDirectory)) {
        Remove-Item -Path $resolvedArtifactDirectory -Recurse -Force
    }
    New-Item -Path $resolvedArtifactDirectory -ItemType Directory -Force | Out-Null
    [void](Invoke-Gh -Arguments @(
            "run", "download", "$($completedRun.databaseId)",
            "--name", "ezcan-ios-ipa", "--dir", $resolvedArtifactDirectory
        ))

    $ipaFiles = @(Get-ChildItem -Path $resolvedArtifactDirectory -Filter "*.ipa" -File -Recurse)
    if ($ipaFiles.Count -eq 0) {
        throw "The workflow succeeded, but no .ipa file was found in $resolvedArtifactDirectory."
    }

    $ipaPath = $ipaFiles[0].FullName
    Set-PipelineProgress -Percent 100 -Status "Complete. IPA downloaded to $ipaPath"
    Write-Progress -Id 1 -Activity "Ezcan iOS IPA pipeline" -Completed
    Write-Host "`nIPA ready: $ipaPath"
    Write-Host "Actions run: $($completedRun.url)"
    Show-CompletionAlert -Title "Ezcan IPA build complete" -Message "The iOS IPA was built and downloaded.`n`n$ipaPath" -Success $true
} catch {
    Write-Progress -Id 1 -Activity "Ezcan iOS IPA pipeline" -Completed
    Show-CompletionAlert -Title "Ezcan IPA build failed" -Message $_.Exception.Message -Success $false
    throw
}