"""
The no-orphan check (SPRINT_PLAN.md, "The connection rule"). It fails when:

  - a module under src/ is not reachable by imports from an entry point (main.py, or a module
    run with `python -m`, listed in ENTRY_POINTS);
  - an API route has no test that calls it;
  - anything outside src/core/config.py reads the environment or a .env file;
  - a model id is written anywhere but src/core/config.py.

It reads the source with ast and needs no running server. CI runs it as its own step, and it
also runs with the rest of the suite.
"""

import ast
import re
from pathlib import Path

from fastapi.routing import APIRoute
from starlette.routing import Mount

from main import app
from src.core.config import OLLAMA_EMBEDDING_MODEL, OLLAMA_LLM_MODEL, Settings

BACKEND_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = BACKEND_DIR / "src"
TESTS_DIR = BACKEND_DIR / "tests"
CONFIG_FILE = SRC_DIR / "core" / "config.py"

# Modules started directly rather than imported
ENTRY_POINTS = {"main", "src.evaluation.evaluate", "src.evaluation.export_feedback", "src.maintenance", "src.reembed",
                "src.ollama_ready"}


def _module_name(path: Path) -> str:
    name = ".".join(path.relative_to(BACKEND_DIR).with_suffix("").parts)
    return name.removesuffix(".__init__")


def _app_files():
    return [BACKEND_DIR / "main.py", *sorted(SRC_DIR.rglob("*.py"))]


def _imports(path: Path, known: set) -> set:
    """The modules of this app that a file imports (from x import y counts y when y is a module)."""
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    # Importing a.b.c also runs a and a.b
    closure = set()
    for name in found:
        parts = name.split(".")
        closure.update(".".join(parts[:i]) for i in range(1, len(parts) + 1))
    return closure & known


def unreachable_modules():
    files = {_module_name(p): p for p in _app_files()}
    reached, todo = set(), [m for m in ENTRY_POINTS if m in files]
    while todo:
        module = todo.pop()
        if module in reached:
            continue
        reached.add(module)
        parents = {".".join(module.split(".")[:i]) for i in range(1, module.count(".") + 1)}  # run first
        todo.extend((_imports(files[module], set(files)) | (parents & set(files))) - reached)
    return sorted(set(files) - reached)


def test_every_module_is_reachable_from_an_entry_point():
    assert unreachable_modules() == [], "modules nothing imports: delete them or wire them in"


def test_the_entry_points_exist():
    files = {_module_name(p) for p in _app_files()}
    assert ENTRY_POINTS <= files


# ── Routes ────────────────────────────────────────────────────────────────────

def _routes():
    routes = set()
    for route in app.routes:
        if isinstance(route, APIRoute):
            routes.update((method.lower(), route.path) for method in route.methods)
        elif isinstance(route, Mount) and route.path == "":
            routes.add(("get", "/"))  # the built React app
    return routes


def _test_sources():
    return "\n".join(p.read_text(encoding="utf-8") for p in TESTS_DIR.rglob("*.py") if p.name != Path(__file__).name)


def routes_without_a_test(routes, sources):
    missing = []
    for method, path in sorted(routes):
        p, m = re.escape(path), re.escape(method)
        patterns = [
            rf"\.{m}\(\s*f?[\"']{p}[\"']",                      # client.get("/api/v1/health")
            rf"\(\s*[\"']{m}[\"']\s*,\s*[\"']{p}[\"']",         # ("delete", "/api/v1/documents")
            rf"\(\s*[\"']{p}[\"']\s*,\s*[\"']{m}[\"']",         # ("/api/v1/documents", "delete")
        ]
        if not any(re.search(pattern, sources) for pattern in patterns):
            missing.append(f"{method.upper()} {path}")
    return missing


def test_every_route_has_a_test_that_calls_it():
    routes = _routes()
    assert ("post", "/api/v1/chat") in routes and ("get", "/") in routes
    assert routes_without_a_test(routes, _test_sources()) == []


def test_the_route_check_notices_a_route_nobody_calls():
    assert routes_without_a_test({("post", "/api/v1/nowhere")}, _test_sources()) == ["POST /api/v1/nowhere"]


# ── Configuration ─────────────────────────────────────────────────────────────

def environment_readers(path: Path):
    """Lines in a file that read the environment or a .env file."""
    hits = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Attribute) and node.attr in {"environ", "getenv", "putenv"}:
            hits.append(node.lineno)
        elif isinstance(node, ast.ImportFrom) and node.module in {"os", "dotenv"} and \
                any(a.name in {"environ", "getenv", "load_dotenv", "dotenv_values"} for a in node.names):
            hits.append(node.lineno)
        elif isinstance(node, ast.Import) and any(a.name == "dotenv" for a in node.names):
            hits.append(node.lineno)
    return hits


def test_only_core_config_reads_the_environment():
    readers = {str(p.relative_to(BACKEND_DIR)): environment_readers(p) for p in _app_files() if p != CONFIG_FILE}
    assert {name: lines for name, lines in readers.items() if lines} == {}


def test_the_environment_check_notices_a_reader(tmp_path):
    sneaky = tmp_path / "sneaky.py"
    sneaky.write_text("import os\nfrom dotenv import load_dotenv\nTOP_K = int(os.environ.get('TOP_K', 5))\n")
    assert environment_readers(sneaky) == [2, 3]


def test_each_model_id_is_written_in_exactly_one_place():
    # Seam checklist: "Config: the model id appears in exactly one place"
    for model_id in (Settings.model_fields["llm_model"].default, Settings.model_fields["embedding_model"].default,
                     OLLAMA_LLM_MODEL, OLLAMA_EMBEDDING_MODEL, Settings.model_fields["rerank_model"].default):
        places = [(p.relative_to(BACKEND_DIR), n) for p in _app_files()
                  for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1) if model_id in line]
        assert places == [(CONFIG_FILE.relative_to(BACKEND_DIR), places[0][1])], (model_id, places)
    outside = [p for p in _app_files() if p != CONFIG_FILE and "gemini-" in p.read_text(encoding="utf-8")]
    assert outside == []
