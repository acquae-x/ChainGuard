from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = PROJECT_ROOT / "Dockerfile"
COMPOSE = PROJECT_ROOT / "docker-compose.yml"
DOCKERIGNORE = PROJECT_ROOT / ".dockerignore"


def test_dockerfile_exists():
    assert DOCKERFILE.exists(), "Dockerfile does not exist"


def test_dockerfile_uses_python313():
    content = DOCKERFILE.read_text(encoding="utf-8")

    assert "python:3.13" in content, "base image must be python:3.13-slim"


def test_dockerfile_is_multistage_non_root_and_excludes_demo_assets():
    content = DOCKERFILE.read_text(encoding="utf-8")

    assert " AS builder" in content
    assert "USER appuser" in content
    assert "COPY --chown=appuser:appgroup src ./src" in content
    assert "demo_assets" not in content


def test_dockerfile_includes_config_and_data():
    content = DOCKERFILE.read_text(encoding="utf-8")

    assert "COPY --chown=appuser:appgroup config ./config" in content, (
        "镜像必须包含 config/(决策链路读 thresholds.yaml,否则生成方案失败)"
    )
    assert "COPY --chown=appuser:appgroup data ./data" in content, (
        "镜像必须包含 data/(审计/经验卡 jsonl 写入目录)"
    )


def test_dockerignore_does_not_exclude_data_dir():
    content = DOCKERIGNORE.read_text(encoding="utf-8")

    lines = [line.strip() for line in content.splitlines()]
    assert "data/" not in lines and "data" not in lines, (
        ".dockerignore 不能整体排除 data/,否则 COPY data ./data 会失败"
    )


def test_compose_mounts_writable_data_volume():
    content = COMPOSE.read_text(encoding="utf-8")

    assert "appdata:/app/data" in content, "api 服务需为 /app/data 挂可写卷"


def _api_service_block(content: str) -> str:
    return content.split("\n  api:", 1)[1].split("\n  web:", 1)[0]


def test_compose_persists_workspace_volume():
    """1-1 回归：.workspace 只存在于镜像层,不挂卷则每次容器重建静默清零。

    落在这里的是租户校准注册表(calibration_registry/<digest>/model_registry.json)
    与导入暂存。丢失不会报错——代码会重建一个空注册表,漂移检测从零开始,
    故障形态是"基线悄悄消失"而不是任何可见异常,因此必须由测试守住。
    """
    content = COMPOSE.read_text(encoding="utf-8")

    assert "workspace:/app/.workspace" in _api_service_block(content), (
        "api 服务必须为 /app/.workspace 挂持久卷"
    )
    volumes = content.split("\nvolumes:", 1)[1]
    assert "\n  workspace:" in volumes, "workspace 必须声明为命名卷"


def test_workspace_paths_the_application_writes_are_under_the_mounted_root():
    """卷挂在 /app/.workspace,因此所有落盘路径都必须在这个前缀之下。

    锁的是"挂载点覆盖了真实写入路径"这个契约:任何一处改成别的根目录,
    持久化就会重新失效,而且同样没有任何可见异常。
    """
    from src.webapi.calibration_governance import _registry_path

    registry = _registry_path("tenant-example")
    assert registry.parts[0] == ".workspace"
    assert registry.parts[1] == "calibration_registry"

    imports_source = (PROJECT_ROOT / "src" / "webapi" / "routers" / "imports_settings.py").read_text(encoding="utf-8")
    assert 'Path(".workspace") / "imports"' in imports_source


def test_backup_covers_workspace_alongside_appdata():
    """校准基线与 appdata 同属丢了不可重建的状态,备份范围必须一致。"""
    backup = (PROJECT_ROOT / "scripts" / "backup-postgres.sh").read_text(encoding="utf-8")
    content = COMPOSE.read_text(encoding="utf-8")

    assert "tar -C /workspace" in backup
    assert "workspace:/workspace:ro" in content


def test_dockerfile_prepares_workspace_subdirectories_for_the_mounted_volume():
    """命名卷首次创建时会继承镜像内该路径的属主,chown 必须在建目录之后。"""
    content = DOCKERFILE.read_text(encoding="utf-8")

    assert "/app/.workspace/calibration_registry" in content
    assert "/app/.workspace/imports" in content
    assert "chown -R appuser:appgroup /app" in content


def test_compose_has_full_stack_services():
    content = COMPOSE.read_text(encoding="utf-8")

    for service in ["postgres:", "migrate:", "api:", "web:", "postgres-backup:"]:
        assert service in content, f"docker-compose.yml missing {service}"
    assert "service_completed_successfully" in content


def test_compose_uses_nginx_and_multi_worker_api_without_default_password():
    content = COMPOSE.read_text(encoding="utf-8")

    assert "}:8080" in content
    assert "--workers" in content
    assert "POSTGRES_PASSWORD:-" not in content
    assert "postgresql+psycopg" in content


def test_dockerignore_excludes_git_and_tests():
    content = DOCKERIGNORE.read_text(encoding="utf-8")

    assert ".git" in content, ".dockerignore must exclude .git"
    assert "tests/" in content or "tests" in content, ".dockerignore must exclude tests"
    assert "__pycache__" in content, ".dockerignore must exclude __pycache__"
