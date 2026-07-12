param(
  [string]$OutputPath = "./chainguard-images.tar"
)

$ErrorActionPreference = 'Stop'
$images = @('postgres:16-alpine')
docker compose config --images | ForEach-Object { if ($_ -and $_ -notmatch '^sha256:') { $images += $_ } }
$images = $images | Sort-Object -Unique
docker save -o $OutputPath $images
Write-Host "已导出 $($images.Count) 个镜像到 $OutputPath"
