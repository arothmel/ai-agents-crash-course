from flask import Flask, session, render_template_string, request
import json
from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_FILE = BASE_DIR / "rag_setup" / "recipes_normalized.jsonl"
MODULE_DIR = BASE_DIR / "multi_agent_chatbot"

for path in (MODULE_DIR, BASE_DIR):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from effective_recipe import build_effective_recipe
from retrieval import build_nutrition_input

app = Flask(__name__)
app.secret_key = "debug-session-key"

def load_rows():
    rows = []
    with open(DATA_FILE, encoding="utf-8") as f:
        for line in f:
            rows.append(json.loads(line))
    return rows


def recipe_rows():
    return [
        r for r in load_rows()
        if r.get("classification") in {"recipe_full", "recipe_partial"}
    ]


def apply_line_swaps(lines, overrides):
    updated = list(lines or [])
    for override in overrides or []:
        action = (override.get("action") or "").lower()
        if action != "swap":
            continue
        target = (override.get("target") or "").strip().lower()
        replacement_meta = override.get("replacement") or {}
        replacement = replacement_meta.get("name") or override.get("replacement_value")
        if not target or not replacement:
            continue
        replaced = False
        new_lines = []
        for line in updated:
            compare = (line or "").strip().lower()
            if not replaced and target in compare:
                new_lines.append(replacement)
                replaced = True
            else:
                new_lines.append(line)
        updated = new_lines
    return updated


@app.route("/")
def index():
    rows = recipe_rows()
    return render_template_string("""
    <h1>Recipes</h1>
    <table border="1" cellpadding="5">
        <tr>
            <th>Title</th>
            <th>Classification</th>
            <th>Stage</th>
        </tr>
        {% for r in rows %}
        <tr>
            <td><a href="/recipe/{{ loop.index0 }}">{{ r.title }}</a></td>
            <td>{{ r.classification }}</td>
            <td>{{ r.stage }}</td>
        </tr>
        {% endfor %}
    </table>
    """, rows=rows)


@app.route("/recipe/<int:idx>", methods=["GET", "POST"])
def recipe(idx):
    rows = recipe_rows()
    r = rows[idx]

    original_lines = list(r.get("ingredient_lines_raw") or [])
    override_key = f"recipe_lines_{idx}"
    has_override = override_key in session
    current_lines = list(session.get(override_key, original_lines))

    if request.method == "POST":
        text = request.form.get("lines", "")
        current_lines = text.splitlines()
        session[override_key] = current_lines
        has_override = True

    test_override = []

    try:
        effective_recipe = build_effective_recipe(r, test_override)
    except Exception as e:
        effective_recipe = {
            "_error": str(e),
            "_note": "build_effective_recipe() failed with current override shape"
        }

    retrieval_recipe = {"ingredient_lines_raw": original_lines}
    if has_override:
        retrieval_recipe["ingredient_lines_current"] = current_lines
    nutrition_input = build_nutrition_input(r.get("id"), retrieval_recipe)

    return render_template_string("""
    <h1>{{ r.title }}</h1>

    <p><b>Classification:</b> {{ r.classification }}</p>
    <p><b>Stage:</b> {{ r.stage }} {% if not r.stage_is_valid %}<span style="color: red;">(invalid)</span>{% endif %}</p>
    <p><b>Servings:</b> {{ r.servings }}</p>

    <h2>Ingredient Lines</h2>
    <p><b>Source:</b> {{ r.ingredient_lines_source }}</p>
    <p><b>Status:</b> {{ r.ingredient_lines_status }}</p>
    <p><b>Ingestion Flags:</b> {{ r.ingestion_flags }}</p>
    <h3>Original</h3>
    <pre>{{ original_lines | tojson(indent=2) }}</pre>

    <h3>Working Copy (Editable)</h3>
    {% if not has_override %}
    <p><em>No saved overrides yet. Editing below will create a session copy.</em></p>
    {% endif %}
    <form method="post">
      <textarea name="lines" rows="25" cols="80">{{ current_lines | join('\n') }}</textarea>
      <br><br>
      <button type="submit">Update</button>
    </form>
    <h3>Preview</h3>
    <pre>{{ current_lines | join('\n') }}</pre>
    
    <p>
      <a href="mailto:?subject=Recipe&body={{ current_lines | join('%0A') | urlencode }}">
        Email this
      </a>
    </p>

    <h3>Lines Sent to Nutrition</h3>
    <p><b>Selected Source:</b> {{ nutrition_input.ingredient_source }}</p>
    <p><b>Status:</b> {{ nutrition_input.status }}{% if nutrition_input.message %} — {{ nutrition_input.message }}{% endif %}</p>
    <p><b>Count:</b> {{ nutrition_input.ingredient_lines | length }}</p>
    <pre>{{ nutrition_input.ingredient_lines | join('\n') }}</pre>
    {% if nutrition_input.ingredient_lines_excluded %}
    <h4>Excluded (Herbs/Spices/Seasonings)</h4>
    <ul>
      {% for item in nutrition_input.ingredient_lines_excluded %}
      <li>[{{ item.classification }}] {{ item.line }}</li>
      {% endfor %}
    </ul>
    {% endif %}

    <h2>Body</h2>
    <pre>{{ r.body }}</pre>

    <h2>Herbs</h2>
    <pre>{{ r.herb_mentions }}</pre>

    <h2>Aromatics</h2>
    <pre>{{ r.aromatic_mentions }}</pre>

    {% if test_override %}
    <h2>Test Override</h2>
    <pre>{{ test_override | tojson(indent=2) }}</pre>
    {% endif %}

    <h2>Effective Recipe</h2>
    <pre>{{ effective_recipe | tojson(indent=2) }}</pre>

    <h2>Raw JSON</h2>
    <pre>{{ r | tojson(indent=2) }}</pre>

    <p><a href="/">← Back</a></p>
    """, r=r, test_override=test_override, effective_recipe=effective_recipe,
        original_lines=original_lines, current_lines=current_lines,
        nutrition_input=nutrition_input)


if __name__ == "__main__":
    app.run(debug=True)
