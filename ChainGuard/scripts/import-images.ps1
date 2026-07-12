param(
  [Parameter(Mandatory = $true)][string]$ImageArchive
)

$ErrorActionPreference = 'Stop'
docker load -i $ImageArchive
Write-Host "离线镜像导入完成。随后执行 docker compose up -d。"
