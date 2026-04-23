$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

$pythonExe = 'python'
$pythonCommand = (Get-Command $pythonExe).Source
$appVersion = '1.0.0.0'
$productName = 'PyChat Agent'
$productBinary = 'PyChat-Agent'
$buildRoot = Join-Path $projectRoot 'build\nuitka'
$releaseRoot = Join-Path $projectRoot 'release'
$finalDir = Join-Path $releaseRoot 'PyChat-Agent-windows-x64'
$zipPath = Join-Path $projectRoot 'PyChat-Agent-windows-x64.zip'

Write-Host '==> Installing Nuitka build dependencies...'
& $pythonCommand -m pip install nuitka ordered-set zstandard

$vcVarsCandidates = @(
    'C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat',
    'C:\Program Files\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat',
    'C:\Program Files (x86)\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat',
    'C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat'
)

$compilerArgs = @()
$clCommand = Get-Command cl.exe -ErrorAction SilentlyContinue
if (-not $clCommand) {
    $vcVarsPath = $vcVarsCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($vcVarsPath) {
        Write-Host "==> Initializing MSVC environment from $vcVarsPath ..."
        $vcEnvironment = & cmd.exe /d /s /c "\"$vcVarsPath\" >nul && set"

        foreach ($line in $vcEnvironment) {
            if ($line -match '^(.*?)=(.*)$') {
                Set-Item -Path ("Env:{0}" -f $matches[1]) -Value $matches[2]
            }
        }

        $clCommand = Get-Command cl.exe -ErrorAction SilentlyContinue
    }
}

if ($clCommand) {
    $compilerArgs += '--msvc=latest'
} else {
    $compilerArgs += '--mingw64'
    $compilerArgs += '--assume-yes-for-downloads'
}

if (Test-Path $buildRoot) {
    Remove-Item $buildRoot -Recurse -Force
}
if (!(Test-Path $releaseRoot)) {
    New-Item -ItemType Directory -Path $releaseRoot | Out-Null
}
if (Test-Path $finalDir) {
    Remove-Item $finalDir -Recurse -Force
}
if (Test-Path $zipPath) {
    Remove-Item $zipPath -Force
}

Write-Host '==> Building standalone Windows package with Nuitka...'
& $pythonCommand -m nuitka `
    --standalone `
    --enable-plugin=pyqt6 `
    --windows-console-mode=disable `
    --remove-output `
    --output-dir=$buildRoot `
    --output-filename=$productBinary `
    --product-name=$productName `
    --file-description='PyChat Agent | LLM chat / agent / tools' `
    --file-version=$appVersion `
    --product-version=$appVersion `
    --company-name='PyChat Contributors' `
    --copyright='Copyright (C) 2026 PyChat Contributors' `
    --windows-icon-from-ico=pycat.ico `
    --include-data-dir=assets=assets `
    --include-data-files=pycat.ico=pycat.ico `
    --include-data-files=LICENSE=LICENSE `
    --include-data-files=README.md=README.md `
    --include-data-files=README_zh.md=README_zh.md `
    @compilerArgs `
    main.py

$distDir = Get-ChildItem -Path $buildRoot -Directory | Where-Object { $_.Name -like '*.dist' } | Select-Object -First 1
if (-not $distDir) {
    throw 'Nuitka build did not produce a .dist directory.'
}

Move-Item -Path $distDir.FullName -Destination $finalDir

Write-Host '==> Creating zip package...'
Compress-Archive -Path $finalDir -DestinationPath $zipPath -Force

Write-Host "Build complete: $zipPath"
