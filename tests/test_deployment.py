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


def test_dockerfile_copies_required_dirs():
    content = DOCKERFILE.read_text(encoding="utf-8")

    for required in [
        "COPY src/",
        "COPY app.py",
        "COPY config/",
        "COPY data/",
        "COPY demo_assets/",
    ]:
        assert required in content, f"Dockerfile missing {required}"


def test_compose_has_both_services():
    content = COMPOSE.read_text(encoding="utf-8")

    assert "streamlit:" in content, "docker-compose.yml missing streamlit service"
    assert "api:" in content, "docker-compose.yml missing api service"


def test_compose_ports_correct():
    content = COMPOSE.read_text(encoding="utf-8")

    assert "8501:8501" in content, "streamlit port mapping is missing"
    assert "8000:8000" in content, "api port mapping is missing"
    assert "0.0.0.0" in content, "services must bind 0.0.0.0"


def test_dockerignore_excludes_git_and_tests():
    content = DOCKERIGNORE.read_text(encoding="utf-8")

    assert ".git" in content, ".dockerignore must exclude .git"
    assert "tests/" in content or "tests" in content, ".dockerignore must exclude tests"
    assert "__pycache__" in content, ".dockerignore must exclude __pycache__"
