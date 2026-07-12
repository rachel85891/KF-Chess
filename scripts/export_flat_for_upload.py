"""Exports the project as a flat, actually-runnable folder of files for
platforms that only accept single-folder uploads (no subfolders).

Python files (.py) are handled one-to-one, not merged: every .py file
(except empty __init__.py package markers) becomes its own file in
upload_flat/, renamed to a unique flat name derived from its project
path (e.g. kungfu_chess/domain/movement/rules.py ->
kungfu_chess_domain_movement_rules.py). Every internal
'from kungfu_chess.a.b.c import X' statement is rewritten to
'from kungfu_chess_a_b_c import X' so it resolves against the new flat
names. main.py keeps its exact name, unprefixed, so it stays the
recognizable entry point - `python main.py` genuinely works standalone
inside upload_flat/, since Python adds a script's own directory to
sys.path automatically. This can't be done by merging multiple modules
into one file per folder (the earlier approach): concatenation order
would silently break any module whose top-level code depends on a
name defined in a file that happens to sort after it.

Non-Python files (fixtures, golden output, requirements-dev.txt, etc.)
have no import statements to rewrite, so they keep the simpler
merge-by-folder treatment: one merged file per folder, real extension
preserved, each original file marked with a '===== FILE: ... ====='
header.

Run from anywhere: `py scripts/export_flat_for_upload.py`
Re-run any time the project changes, before re-uploading.
"""

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR_NAME = "upload_flat"
FALLBACK_EXTENSION = ".txt"
ENTRY_POINT_NAME = "main.py"
INTERNAL_PACKAGE_PREFIX = "kungfu_chess"

# Extensions whose comment syntax we know, so FILE headers in merged
# non-Python files can be written as real comments where possible.
COMMENT_PREFIXES = {".py": "#"}

EXCLUDED_DIR_NAMES = {".git", ".claude", "__pycache__", ".pytest_cache", "htmlcov", OUTPUT_DIR_NAME}
EXCLUDED_FILE_NAMES = {".coverage"}

_IMPORT_PATTERN = re.compile(rf"from {INTERNAL_PACKAGE_PREFIX}\.([\w.]+) import")

_skipped_binary_files: list[Path] = []


def _read_text_or_none(path: Path) -> str | None:
    """Returns the file's text, or None (and records it as skipped) if
    it isn't valid UTF-8 text - e.g. a stray zip/binary someone dropped
    in the project root. One unreadable file must not crash the whole
    export."""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        _skipped_binary_files.append(path)
        return None


def _is_excluded(path: Path) -> bool:
    return any(part in EXCLUDED_DIR_NAMES for part in path.relative_to(PROJECT_ROOT).parts)


def _collect_project_files() -> list[Path]:
    files = []
    for path in PROJECT_ROOT.rglob("*"):
        if path.is_dir() or _is_excluded(path) or path.name in EXCLUDED_FILE_NAMES:
            continue
        files.append(path)
    return files


def _flat_module_name(relative_posix_path: str) -> str:
    """kungfu_chess/domain/movement/rules.py -> kungfu_chess_domain_movement_rules"""
    return relative_posix_path[: -len(".py")].replace("/", "_")


def _rewrite_internal_imports(content: str) -> str:
    return _IMPORT_PATTERN.sub(
        lambda m: f"from {INTERNAL_PACKAGE_PREFIX}_{m.group(1).replace('.', '_')} import", content
    )


def _flat_py_file_name(path: Path) -> str | None:
    """Returns the flat output filename for a .py file, or None if it
    should be skipped entirely (empty __init__.py package markers)."""
    if path.name == ENTRY_POINT_NAME and path.parent == PROJECT_ROOT:
        return ENTRY_POINT_NAME
    if path.name == "__init__.py":
        return None
    return _flat_module_name(path.relative_to(PROJECT_ROOT).as_posix()) + ".py"


def _write_python_files(py_files: list[Path], output_dir: Path) -> list[tuple[str, int]]:
    written = []
    seen_names: dict[str, Path] = {}

    for path in sorted(py_files, key=lambda p: p.relative_to(PROJECT_ROOT).as_posix()):
        flat_name = _flat_py_file_name(path)
        if flat_name is None:
            continue

        if flat_name in seen_names:
            raise RuntimeError(f"Flat name collision: {path} and {seen_names[flat_name]} both map to {flat_name}")
        seen_names[flat_name] = path

        content = _read_text_or_none(path)
        if content is None:
            continue

        rewritten = _rewrite_internal_imports(content)
        (output_dir / flat_name).write_text(rewritten, encoding="utf-8")
        written.append((flat_name, 1))

    return written


def _common_extension(files: list[Path]) -> str:
    extensions = {f.suffix for f in files}
    if len(extensions) == 1:
        return extensions.pop()
    return FALLBACK_EXTENSION


def _merged_file_name(directory: Path, extension: str) -> str:
    relative = directory.relative_to(PROJECT_ROOT)
    stem = "root" if relative == Path(".") else ".".join(relative.parts)
    return stem + extension


def _file_header(relative_path: str, extension: str) -> str:
    marker = f"===== FILE: {relative_path} ====="
    comment_prefix = COMMENT_PREFIXES.get(extension)
    return f"{comment_prefix} {marker}" if comment_prefix else marker


def _write_merged_non_python_files(non_py_files: list[Path], output_dir: Path) -> list[tuple[str, int]]:
    files_by_dir: dict[Path, list[Path]] = {}
    for path in non_py_files:
        files_by_dir.setdefault(path.parent, []).append(path)

    written = []
    for directory in sorted(files_by_dir, key=lambda d: d.relative_to(PROJECT_ROOT).as_posix()):
        files = files_by_dir[directory]
        extension = _common_extension(files)
        merged_name = _merged_file_name(directory, extension)

        sections = []
        for file_path in sorted(files, key=lambda p: p.name):
            content = _read_text_or_none(file_path)
            if content is None:
                continue
            relative_path = file_path.relative_to(PROJECT_ROOT).as_posix()
            header = _file_header(relative_path, extension)
            sections.append(f"{header}\n{content}")

        if not sections:
            continue

        (output_dir / merged_name).write_text("\n".join(sections), encoding="utf-8")
        written.append((merged_name, len(sections)))

    return written


def main() -> None:
    output_dir = PROJECT_ROOT / OUTPUT_DIR_NAME
    output_dir.mkdir(exist_ok=True)
    for existing in output_dir.iterdir():
        if existing.is_file():
            existing.unlink()

    all_files = _collect_project_files()
    py_files = [f for f in all_files if f.suffix == ".py"]
    non_py_files = [f for f in all_files if f.suffix != ".py"]

    written = _write_python_files(py_files, output_dir)
    written += _write_merged_non_python_files(non_py_files, output_dir)
    written.sort(key=lambda item: item[0])

    print(f"Wrote {len(written)} files to {output_dir}:")
    for name, file_count in written:
        suffix = "" if file_count == 1 else f"  ({file_count} files merged)"
        print(f"  {name}{suffix}")
    print(f"\nEntry point: {output_dir / ENTRY_POINT_NAME}")

    if _skipped_binary_files:
        print(f"\nSkipped {len(_skipped_binary_files)} non-text file(s) (not valid UTF-8, left out of the export):")
        for path in _skipped_binary_files:
            print(f"  {path.relative_to(PROJECT_ROOT).as_posix()}")


if __name__ == "__main__":
    main()
