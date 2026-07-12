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
