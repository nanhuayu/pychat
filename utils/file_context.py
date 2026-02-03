import os

# Try to import pathspec for gitignore support
try:
    import pathspec
except ImportError:
    pathspec = None

def get_file_tree(root_path: str, max_depth: int = 2) -> str:
    """
    Generates a visual file tree structure for the given root path,
    respecting .gitignore if present (excluding ignored files).
    """
    root_path = os.path.abspath(root_path)
    if not os.path.exists(root_path):
        return ""

    # Load .gitignore patterns
    gitignore_path = os.path.join(root_path, ".gitignore")
    ignore_spec = None
    if pathspec and os.path.exists(gitignore_path):
        try:
            with open(gitignore_path, "r", encoding="utf-8") as f:
                ignore_spec = pathspec.PathSpec.from_lines("gitwildmatch", f)
        except Exception:
            pass

    # Default ignores (always applied)
    default_ignores = {
        ".git", "__pycache__", "node_modules", ".DS_Store", "*.pyc", ".vscode", ".idea", "venv", "env", "dist", "build", "coverage"
    }

    tree_lines = []

    def _is_ignored(path: str) -> bool:
        name = os.path.basename(path)
        
        # Check defaults
        if name in default_ignores:
            return True
        if name.endswith(".pyc"):
            return True
        
        # Check pathspec
        if ignore_spec:
            rel_path = os.path.relpath(path, root_path)
            # pathspec expects relative paths (and sometimes / separators)
            rel_path = rel_path.replace(os.sep, "/")
            if ignore_spec.match_file(rel_path):
                return True
        return False

    def _walk(current_path: str, current_depth: int, prefix: str = ""):
        if current_depth > max_depth:
            return

        try:
            # Sort directories first, then files
            entries = sorted(os.listdir(current_path))
        except OSError:
            return

        # Filter ignored
        filtered_entries = []
        for entry in entries:
            full_path = os.path.join(current_path, entry)
            if not _is_ignored(full_path):
                filtered_entries.append(entry)

        count = len(filtered_entries)
        for i, entry in enumerate(filtered_entries):
            is_last = (i == count - 1)
            full_path = os.path.join(current_path, entry)
            
            connector = "└── " if is_last else "├── "
            tree_lines.append(f"{prefix}{connector}{entry}")

            if os.path.isdir(full_path):
                new_prefix = prefix + ("    " if is_last else "│   ")
                # If we are at max_depth, we don't recurse, but maybe we should indicate truncation?
                # The user requested structure info, so maybe just standard recursion.
                _walk(full_path, current_depth + 1, new_prefix)

    tree_lines.append(os.path.basename(root_path) + "/")
    _walk(root_path, 1)
    
    return "\n".join(tree_lines)
