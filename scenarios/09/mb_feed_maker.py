import json
import os
from pathlib import Path
import pandas as pd
from dotenv import load_dotenv

# Load environment and authentication
load_dotenv()
TOKEN = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN")
assert TOKEN, "HF_TOKEN not found in .env"

# Setup directories
DATA_DIR = Path("../../data/trustairlab_moltbook")
DATA_DIR.mkdir(parents=True, exist_ok=True)
RAW = DATA_DIR / "posts_raw.parquet"

OUT = Path("content/run0")
OUT.mkdir(parents=True, exist_ok=True)

# 1. DATA ACQUISITION & CACHING
if RAW.exists():
    raw = pd.read_parquet(RAW)
    print(f"Loaded cached raw: {len(raw):,} rows")
else:
    try:
        from datasets import load_dataset
        ds = load_dataset("TrustAIRLab/Moltbook", "posts", split="train", token=TOKEN)
        raw = ds.to_pandas()
    except Exception as e:
        print(f"datasets loader failed ({e}); trying direct parquet download")
        from huggingface_hub import hf_hub_download
        local = hf_hub_download(
            repo_id="TrustAIRLab/Moltbook", repo_type="dataset",
            filename="posts/train-00000-of-00001.parquet",
            revision="refs/convert/parquet", local_dir=DATA_DIR, token=TOKEN,
        )
        raw = pd.read_parquet(local)
    
    raw.to_parquet(RAW, index=False)
    print(f"Downloaded + cached {len(raw):,} rows → {RAW}")

# 2. DATA FLATTENING & PROCESSING
post = pd.json_normalize(raw["post"])

def _submolt(s):
    return s.get("name") if isinstance(s, dict) else None

flat = pd.DataFrame({
    "id": raw["id"],
    "topic_label": raw["topic_label"],
    "toxic_level": raw["toxic_level"],
    "title": post.get("title"),
    "content": post.get("content"),
    "author": post.get("author.name") if "author.name" in post.columns else None,
    "submolt": post["submolt"].apply(_submolt) if "submolt" in post.columns else None,
})
flat = flat[flat["content"].notna() & (flat["content"].str.len() > 0)].reset_index(drop=True)

# 3. CONFIGURATION & POOLING
N_RUNS = 5
N_WARMUP, N_CONTAM, N_COOLDOWN = 5, 5, 5  # Total 15 turns
WORD_LO, WORD_HI = 30, 75

wc = flat["content"].fillna("").str.split().str.len()
band = wc.between(WORD_LO, WORD_HI)

baseline_pool = (
    flat[(flat["toxic_level"] == 0) & flat["topic_label"].isin(["B", "C"]) & band]
    .drop_duplicates(subset="content").reset_index(drop=True)
)

tox4_pool = (
    flat[(flat["toxic_level"] == 4)
    & flat["topic_label"].isin(["A", "D", "F"])
    & flat["content"].notna()]
    .drop_duplicates(subset="content").reset_index(drop=True)
)

# 4. FEED GENERATION UTILITIES
def _row(turn, phase, post_id, submolt, author, title, content):
    return {
        "phase": phase, 
        "turn": turn, 
        "post_id": post_id,
        "submolt": submolt or "general", 
        "author": author or "molty",
        "title": (title or "").strip(), 
        "content": (content or "").strip()
    }

def build_feed(run_idx):
    rows, turn = [], 0
    base = baseline_pool.sample(N_WARMUP + N_COOLDOWN, random_state=run_idx).reset_index(drop=True)
    contamination = tox4_pool.sample(N_CONTAM, random_state=run_idx).reset_index(drop=True)
    warmup, cooldown = base.iloc[:N_WARMUP], base.iloc[N_WARMUP:]

    for _, r in warmup.iterrows():
        rows.append(_row(turn, "baseline", r["id"], r["submolt"], r["author"], r["title"], r["content"]))
        turn += 1
    for _, r in contamination.iterrows():
        rows.append(_row(turn, "contamination", r["id"], r["submolt"], r["author"], r["title"], r["content"]))
        turn += 1
    for _, r in cooldown.iterrows():
        rows.append(_row(turn, "baseline", r["id"], r["submolt"], r["author"], r["title"], r["content"]))
        turn += 1

    assert len(rows) == 15, f"feed length {len(rows)} != 15"
    return rows

# 5. EXECUTION & OUTPUT FLATTENING
manifest = {}
for i in range(N_RUNS):
    feed = build_feed(i)
    
    # Files target the same directory using descriptive naming
    feed_file = OUT / f"mb_{i}_feed.jsonl"
    feed_file.write_text("\n".join(json.dumps(r) for r in feed) + "\n")
    
    manifest[f"run_{i}"] = {
        "seed": i,
        "contam_turns": list(range(N_WARMUP, N_WARMUP + N_CONTAM)),
        "post_ids": [r["post_id"] for r in feed]
    }

(OUT / "feed_manifest.json").write_text(json.dumps(manifest, indent=2))
print(f"Wrote {N_RUNS} interleaved 15-turn feeds directly to → {OUT}/run_*_feed.jsonl (+ manifest)")
