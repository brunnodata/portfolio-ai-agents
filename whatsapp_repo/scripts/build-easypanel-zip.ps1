# Gera ZIPs prontos para deploy no Easypanel (backend e dashboard separados).
# Uso:
#   .\scripts\build-easypanel-zip.ps1              # gera os dois
#   .\scripts\build-easypanel-zip.ps1 -Target backend
#   .\scripts\build-easypanel-zip.ps1 -Target dashboard

param(
    [ValidateSet("backend", "dashboard", "all")]
    [string]$Target = "all",

    [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
if (-not $OutputDir) {
    $OutputDir = Join-Path $RepoRoot "dist\easypanel"
}

$ExcludeDirNames = @(
    "node_modules",
    ".next",
    "__pycache__",
    ".venv",
    ".git",
    "dist",
    "backups",
    "admin_files"
)

$ExcludeFileNames = @(
    ".env",
    ".DS_Store"
)

$ExcludeFilePatterns = @(
    "*.pyc",
    "*.pyo",
    "*.log",
    "Thumbs.db"
)

function Test-ExcludedPath {
    param(
        [string]$RelativePath,
        [string]$Name,
        [bool]$IsDirectory
    )

    if ($ExcludeDirNames -contains $Name) {
        return $true
    }

    if (-not $IsDirectory -and $ExcludeFileNames -contains $Name) {
        return $true
    }

    if (-not $IsDirectory) {
        foreach ($pattern in $ExcludeFilePatterns) {
            if ($Name -like $pattern) {
                return $true
            }
        }
    }

    return $false
}

function Copy-DeploySource {
    param(
        [string]$SourceDir,
        [string]$DestinationDir
    )

    if (-not (Test-Path $SourceDir)) {
        throw "Diretorio de origem nao encontrado: $SourceDir"
    }

    if (Test-Path $DestinationDir) {
        Remove-Item -Path $DestinationDir -Recurse -Force
    }

    New-Item -ItemType Directory -Path $DestinationDir -Force | Out-Null

    $queue = [System.Collections.Generic.Queue[object]]::new()
    $queue.Enqueue([pscustomobject]@{
        Source = $SourceDir
        Dest   = $DestinationDir
        Rel    = ""
    })

    while ($queue.Count -gt 0) {
        $current = $queue.Dequeue()
        $children = Get-ChildItem -LiteralPath $current.Source -Force

        foreach ($child in $children) {
            $relPath = if ($current.Rel) { Join-Path $current.Rel $child.Name } else { $child.Name }

            if (Test-ExcludedPath -RelativePath $relPath -Name $child.Name -IsDirectory:$child.PSIsContainer) {
                continue
            }

            $destPath = Join-Path $current.Dest $child.Name

            if ($child.PSIsContainer) {
                New-Item -ItemType Directory -Path $destPath -Force | Out-Null
                $queue.Enqueue([pscustomobject]@{
                    Source = $child.FullName
                    Dest   = $destPath
                    Rel    = $relPath
                })
            }
            else {
                Copy-Item -LiteralPath $child.FullName -Destination $destPath -Force
            }
        }
    }
}

function Write-EasypanelGuide {
    param(
        [string]$Path,
        [string]$ServiceName,
        [int]$Port,
        [string[]]$EnvVars,
        [string[]]$ExtraNotes = @()
    )

    $lines = @(
        "GastoZap - Deploy no Easypanel ($ServiceName)",
        "============================================",
        "",
        "1. No Easypanel: Add Service > App > Source: Upload (ZIP)",
        "2. Envie este arquivo ZIP",
        "3. Build method: Dockerfile (na raiz do ZIP)",
        "4. Proxy port: $Port",
        "",
        "Variaveis de ambiente obrigatorias:",
        ""
    )

    foreach ($var in $EnvVars) {
        $lines += "- $var"
    }

    if ($ExtraNotes.Count -gt 0) {
        $lines += ""
        $lines += "Observacoes:"
        foreach ($note in $ExtraNotes) {
            $lines += "- $note"
        }
    }

    $lines += ""
    $lines += "PostgreSQL: crie um servico PostgreSQL separado no mesmo projeto."
    $lines += "Use a connection string interna do painel em DATABASE_URL (somente backend)."

    Set-Content -Path $Path -Value $lines -Encoding UTF8
}

function New-DeployZip {
    param(
        [string]$ServiceKey,
        [string]$SourceRelativePath,
        [string]$ZipPrefix,
        [scriptblock]$GuideWriter
    )

    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $sourceDir = Join-Path $RepoRoot $SourceRelativePath
    $stagingRoot = Join-Path $env:TEMP "gastozap-easypanel-$ServiceKey-$timestamp"
    $stagingDir = Join-Path $stagingRoot "app"
    $zipName = "$ZipPrefix-$timestamp.zip"
    $zipPath = Join-Path $OutputDir $zipName

    try {
        Write-Host ""
        Write-Host "[$ServiceKey] Preparando pacote..." -ForegroundColor Cyan
        Copy-DeploySource -SourceDir $sourceDir -DestinationDir $stagingDir

        if (-not (Test-Path (Join-Path $stagingDir "Dockerfile"))) {
            throw "Dockerfile nao encontrado em $SourceRelativePath"
        }

        & $GuideWriter -StagingDir $stagingDir

        if (Test-Path $zipPath) {
            Remove-Item -Path $zipPath -Force
        }

        Compress-Archive -Path (Join-Path $stagingDir "*") -DestinationPath $zipPath -CompressionLevel Optimal

        $sizeMb = [math]::Round((Get-Item $zipPath).Length / 1MB, 2)
        Write-Host "[$ServiceKey] ZIP gerado: $zipPath ($sizeMb MB)" -ForegroundColor Green
        return $zipPath
    }
    finally {
        if (Test-Path $stagingRoot) {
            Remove-Item -Path $stagingRoot -Recurse -Force
        }
    }
}

New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

$generated = @()

if ($Target -in @("backend", "all")) {
    $generated += New-DeployZip `
        -ServiceKey "backend" `
        -SourceRelativePath "backend" `
        -ZipPrefix "gastozap-backend-easypanel" `
        -GuideWriter {
            param($StagingDir)

            Write-EasypanelGuide `
                -Path (Join-Path $StagingDir "EASYPANEL.txt") `
                -ServiceName "Backend API" `
                -Port 8000 `
                -EnvVars @(
                    "DATABASE_URL=postgresql+asyncpg://user:pass@nome-servico-postgres:5432/gastozap"
                    "EVOLUTION_API_URL=https://sua-evolution-api"
                    "EVOLUTION_API_KEY=..."
                    "EVOLUTION_INSTANCE=gastozap"
                    "WEBHOOK_SECRET=..."
                    "OPENAI_API_KEY=sk-..."
                    "ALLOWED_PHONE_NUMBERS=5511999999999"
                    "DASHBOARD_USERNAME=admin"
                    "DASHBOARD_PASSWORD=..."
                    "CORS_ORIGINS=https://seu-dashboard.easypanel.host"
                    "API_SECRET_KEY=..."
                ) `
                -ExtraNotes @(
                    "Webhook Evolution: POST https://seu-backend/webhook/evolution"
                    "Header: x-webhook-secret = WEBHOOK_SECRET"
                )
        }
}

if ($Target -in @("dashboard", "all")) {
    $generated += New-DeployZip `
        -ServiceKey "dashboard" `
        -SourceRelativePath "dashboard" `
        -ZipPrefix "gastozap-dashboard-easypanel" `
        -GuideWriter {
            param($StagingDir)

            Write-EasypanelGuide `
                -Path (Join-Path $StagingDir "EASYPANEL.txt") `
                -ServiceName "Dashboard Web" `
                -Port 3000 `
                -EnvVars @(
                    "NEXT_PUBLIC_API_URL=https://seu-backend.easypanel.host"
                ) `
                -ExtraNotes @(
                    "NEXT_PUBLIC_API_URL e usada no build do Next.js."
                    "Defina a variavel antes do deploy e refaca o build ao mudar a URL."
                )
        }
}

Write-Host ""
Write-Host "Concluido. Arquivos gerados:" -ForegroundColor Green
foreach ($file in $generated) {
    Write-Host "  - $file"
}

Write-Host ""
Write-Host "Proximo passo no Easypanel:" -ForegroundColor Yellow
Write-Host "  1. Crie PostgreSQL (servico nativo)"
Write-Host "  2. Crie App Backend com o ZIP do backend (porta 8000)"
Write-Host "  3. Crie App Dashboard com o ZIP do dashboard (porta 3000)"
