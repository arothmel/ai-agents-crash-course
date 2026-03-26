"""Compatibility shim for the recipe loader.

Historically this script loaded calorie data. It now delegates to
`recipe_loader.main` so existing documentation still works.
"""

from recipe_loader import main


if __name__ == "__main__":
    main()
