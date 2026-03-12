import csv
import re
from pathlib import Path
import chromadb

chroma = chromadb.PersistentClient(path="../chroma")

# create or reuse collection
collection = chroma.get_or_create_collection("nutrition_db")

with open("../data/calories.csv", newline="", encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)

    docs = []
    metas = []
    ids = []

    for i, row in enumerate(reader):
        food = row["FoodItem"]
        category = row["FoodCategory"]

        calories = int(re.search(r"\d+", row["Cals_per100grams"]).group())

        docs.append(f"{food} has {calories} calories per 100g")
        metas.append({
            "food_item": food.lower(),
            "food_category": category.lower(),
            "calories_per_100g": calories
        })
        ids.append(f"food_{i}")

collection.add(documents=docs, metadatas=metas, ids=ids)

print("Loaded", len(ids), "foods into nutrition_db")
