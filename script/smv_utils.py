def load_smv(path):
    try:
        with open(path, "r") as f:
            return f.read()
    except FileNotFoundError:
        raise ValueError(f"SMV file not found: {path}")

def save_smv(path, content):
    with open(path, "w") as f:
        f.write(content)


def find_module(content, module_name):
    """
    Returns (start_index, end_index) of MODULE <module_name>
    """
    lines = content.splitlines(keepends=True)

    start = None

    for i, line in enumerate(lines):
        if line.strip().startswith(f"MODULE {module_name}"):
            start = i
            break

    if start is None:
        raise ValueError(f"MODULE {module_name} not found")

    for j in range(start + 1, len(lines)):
        if lines[j].strip().startswith("MODULE "):
            return start, j

    return start, len(lines)