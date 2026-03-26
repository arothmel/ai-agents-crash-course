# Data Directory

This directory contains datasets used for nutrition-related AI applications.

## Datasets

### Nutrition Q&A Dataset
- **File**: `questions_output.txt`
- **Source**: [RaniRahbani/nutritionist](https://huggingface.co/datasets/RaniRahbani/nutritionist) dataset from Hugging Face
- **S3 URL**: https://nutrition-datasets.s3.amazonaws.com/questions_output.txt
- **License**: Apache 2.0
- **Description**: A plain-text version of the nutritionist Q&A dataset

### Calories Dataset
- **File**: `calories.csv`
- **Source**: [Calories in Food Items per 100 grams](https://www.kaggle.com/datasets/kkhandekar/calories-in-food-items-per-100-grams) from Kaggle
- **S3 URL**: https://nutrition-datasets.s3.amazonaws.com/calories.csv
- **License**: CC0 Public Domain
- **Description**: Comprehensive dataset containing calorie information for various food items per 100 grams, including food categories, calories, and kilojoules

### Mediterranean EuroFIR Dataset
- **Maintained file**: `eurofir_mediterranean.csv` – curated EuroFIR-style records for ~50 Mediterranean ingredients (kcal/macros per 100 g + sourcing notes). Edit this file when you add or tweak foods.
- **Derived file**: `calories_mediterranean.csv` – compatibility export that mirrors the legacy `calories.csv` schema so older loaders keep working.
- **Regeneration command**: `python rag_setup/convert_eurofir_to_calories.py`
- **Vector store**: after regenerating the compatibility CSV, ingest the EuroFIR source into `./chroma_mediterranean/` with `python rag_setup/enrich_nutrition_db.py --chroma-path ./chroma_mediterranean`
