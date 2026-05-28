import re

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
    """Returns (start_index, end_index) of MODULE <module_name>"""
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

def get_module_text(smv_content, module_name):
    """Extract the full text of a named MODULE from an SMV file."""
    start, end = find_module(smv_content, module_name)
    lines = smv_content.splitlines(keepends=True)
    return ''.join(lines[start:end])


def strip_main_module(smv_content):
    """Remove MODULE main from the nominal SMV content."""
    result = re.sub(
        r'\n*--[^\n]*\n--[^\n]*[Mm]ain[^\n]*\n--[^\n]*\nMODULE main.*',
        '',
        smv_content,
        flags=re.DOTALL
    )
    if 'MODULE main' in result:
        result = re.sub(r'\n*MODULE main.*', '', result, flags=re.DOTALL)

    return result.rstrip()
