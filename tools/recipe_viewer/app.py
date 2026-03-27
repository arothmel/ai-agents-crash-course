from flask import Flask, render_template_string
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_FILE = BASE_DIR / "rag_setup" / "recipes_normalized.jsonl"

app = Flask(__name__)


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


@app.route("/recipe/<int:idx>")
def recipe(idx):
    rows = recipe_rows()
    r = rows[idx]

    return render_template_string("""
    <h1>{{ r.title }}</h1>

    <p><b>Classification:</b> {{ r.classification }}</p>
    <p><b>Stage:</b> {{ r.stage }}</p>
    <p><b>Servings:</b> {{ r.servings }}</p>

    <h2>Body</h2>
    <pre>{{ r.body }}</pre>

    <h2>Herbs</h2>
    <pre>{{ r.herb_mentions }}</pre>

    <h2>Aromatics</h2>
    <pre>{{ r.aromatic_mentions }}</pre>

    <h2>Raw JSON</h2>
    <pre>{{ r | tojson(indent=2) }}</pre>

    <p><a href="/">← Back</a></p>
    """, r=r)


if __name__ == "__main__":
    app.run(debug=True)

