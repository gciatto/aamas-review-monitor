#!/usr/bin/env bash
# Renames the template's project and package after the given name (run by init.yml).
# Rewrites every tracked text file mentioning the template names, except this script.
# If an author is given, it replaces the `authors` list in pyproject.toml.
set -euo pipefail

TEMPLATE_PROJECT_NAME="template-python-project-uv"
TEMPLATE_MODULE_NAME="main_package"

if [[ $# -lt 1 || $# -gt 3 ]]; then
    echo "Usage: $0 <new-project-name> [<author-name> [<author-email>]]" >&2
    exit 1
fi

PROJECT_NAME=$1

# PEP 508 project name; this also rules out characters special to sed.
if [[ ! "$PROJECT_NAME" =~ ^[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?$ ]]; then
    echo "Error: '$PROJECT_NAME' is not a valid Python project name" >&2
    exit 1
fi

# PEP 503 normalization, with '_' as separator; identifiers cannot start with a digit.
MODULE_NAME=$(printf "%s" "$PROJECT_NAME" | tr "[:upper:]" "[:lower:]" | sed -E "s/[-_.]+/_/g")
if [[ "$MODULE_NAME" =~ ^[0-9] ]]; then
    MODULE_NAME="_$MODULE_NAME"
fi

cd "$(dirname "$0")"

if [[ ! -d "$TEMPLATE_MODULE_NAME" ]]; then
    echo "Error: $TEMPLATE_MODULE_NAME/ not found; was the project already renamed?" >&2
    exit 1
fi

# Valid identifiers can still be unimportable (keywords) or shadow the standard library.
python3 - "$MODULE_NAME" <<'EOF'
import keyword, sys

name = sys.argv[1]
if keyword.iskeyword(name):
    sys.exit(f"Error: '{name}' is a Python keyword")
if name in sys.stdlib_module_names:
    sys.exit(f"Error: '{name}' would shadow the standard library module")
EOF

# Otherwise `mv` would move the package inside the existing path (e.g. tests/).
if [[ "$MODULE_NAME" != "$TEMPLATE_MODULE_NAME" && -e "$MODULE_NAME" ]]; then
    echo "Error: '$MODULE_NAME' already exists in the repository" >&2
    exit 1
fi

if [[ $# -ge 2 ]]; then
    # TOML basic strings accept JSON-escaped text.
    python3 - "$2" "${3:-}" <<'EOF'
import json, re, sys
from pathlib import Path

name, email = sys.argv[1:]
author = f"name = {json.dumps(name)}" + (f", email = {json.dumps(email)}" if email else "")
path = Path("pyproject.toml")
authors = f"authors = [\n    {{ {author} }}\n]"
text, n = re.subn(r"(?ms)^authors = \[.*?^\]", lambda _: authors, path.read_text())
if n != 1:
    sys.exit("Error: no `authors = [...]` list in pyproject.toml")
path.write_text(text)
EOF
fi

git grep -lzI -F -e "$TEMPLATE_PROJECT_NAME" -e "$TEMPLATE_MODULE_NAME" -- . ':!rename-template.sh' \
    | while IFS= read -r -d '' FILE; do
        # -i.bak works with both GNU and BSD sed
        sed -i.bak -e "s/$TEMPLATE_MODULE_NAME/$MODULE_NAME/g" \
            -e "s/$TEMPLATE_PROJECT_NAME/$PROJECT_NAME/g" "$FILE"
        rm "$FILE.bak"
        echo "Updated $FILE"
    done

if [[ "$MODULE_NAME" != "$TEMPLATE_MODULE_NAME" ]]; then
    mv "$TEMPLATE_MODULE_NAME" "$MODULE_NAME"
fi

echo "Renamed project to '$PROJECT_NAME' with Python module '$MODULE_NAME'."
