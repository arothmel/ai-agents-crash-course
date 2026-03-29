import sys, json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from nutrition_lookup import NutritionLookup

lookup = NutritionLookup()
print(json.dumps(lookup.lookup('chickpeas'), indent=2))
