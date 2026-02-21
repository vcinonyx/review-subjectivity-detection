# Opinion Analysis — Subjectivity Detection in Peer Reviews

A research project comparing rule-based and ML-based approaches to detecting subjective language in academic peer reviews, using data collected from the OpenReview platform.

---

## Project Structure

```
Opinion_Analysis/
├── data/
│   ├── eval_dataset.csv
│   └── test_dataset.csv
├── results/
│   ├── mdebertav3_results.csv
│   ├── qwen3_1_7b_results.csv
│   ├── qwen3_8b_results.csv
│   ├── qwen3_14b_results.csv
│   ├── disagreements.csv
│   └── unanimous_wrong.csv
├── templates/
│   ├── index.html
│   └── reviews.html
├── app.py
├── main.py
├── build_eval_dataset.py
├── mdeberta_subjectivity_eval.ipynb
└── qwen_subjectivity_eval.ipynb
```

---

## Data

### `data/eval_dataset.csv`

The evaluation dataset collected from ICLR 2026 peer reviews via the OpenReview API. It contains sentences classified as either **subjective** or **objective**. Subjective sentences are those that contain at least one of a predefined set of linguistic markers (e.g. hedges, reviewer beliefs, evaluative language). Objective sentences are those with no match against these keyword patterns. Columns include: `paper_id`, `paper_title`, `reviewer`, `field`, `sentence`, `matched_markers`, and `label`.

### `data/test_dataset.csv`

A curated subset of 100 sentences drawn from `eval_dataset.csv`, used as the held-out test set for all model evaluations in this project.

---

## Notebooks

### `mdeberta_subjectivity_eval.ipynb`

Evaluates the [`GroNLP/mdebertav3-subjectivity-english`](https://huggingface.co/GroNLP/mdebertav3-subjectivity-english) model — a fine-tuned mDeBERTa v3 classifier for subjectivity detection in English.

### `qwen_subjectivity_eval.ipynb`

Evaluates three sizes of the Qwen3 instruction-tuned LLM family: **1.7B**, **8B**, and **14B**. Each model is prompted to classify each sentence as subjective or objective and to provide a reasoning chain and natural-language explanation alongside its prediction.

---

## Results

The `results/` folder contains one CSV per model evaluated on `test_dataset.csv`.

### `mdebertav3_results.csv`

Output from the mDeBERTa classifier. Columns: `sentence`, `ground_truth`, `label` (predicted), `confidence`, `correct`.

### `qwen3_1_7b_results.csv` / `qwen3_8b_results.csv` / `qwen3_14b_results.csv`

Output from each Qwen3 model. Columns: `sentence`, `ground_truth`, `label` (predicted), `reasoning`, `explanation`, `confidence`.

### `disagreements.csv`

Sentences where the three Qwen models did not agree with one another on the predicted label.

### `unanimous_wrong.csv`

Sentences where all three Qwen models agreed on a prediction but were collectively wrong relative to the gold label.

---

## App

`app.py` is a Flask web application providing an interactive interface for subjectivity analysis.

**Features:**

- **Text analysis** — paste any review text and receive sentence-level subjectivity labels, with matched keyword markers highlighted.

- **Live OpenReview streaming** — enter a conference venue and stream peer reviews directly from the OpenReview API, with subjective sentences extracted and displayed.

Run locally with:

```bash
python app.py
```

The app is then available at `http://localhost:5000`.
