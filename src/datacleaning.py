import os
import re
import pandas as pd

current_directory = os.path.dirname(os.path.abspath(__file__))
csv_path = os.path.join(current_directory, "final_merged_dataset.csv")
backup_path = os.path.join(current_directory, "final_merged_dataset.backup.csv")

df = pd.read_csv(csv_path)

def clean_list_like_text(val):
    if pd.isna(val):
        return ""
    s = str(val)
    s = s.replace("[", "").replace("]", "").replace("'", "").replace('"', "")
    s = re.sub(r"\s*,\s*", ", ", s)   # normalize comma spacing
    s = re.sub(r"\s+", " ", s).strip()
    return s

def clean_description(val):
    if pd.isna(val):
        return ""
    s = str(val)

    # Replace hyphens connecting words with spaces.
    s = re.sub(r"(?<=\w)-(?=\w)", " ", s)

    # Remove full sentence starting with "shop"
    s = re.sub(r"(?i)\bshop\b[^.!?]*(?:[.!?]|$)", " ", s)

    # Remove phrases
    s = re.sub(r"(?i)\bwhat\s*it\s*is\s*:?", " ", s)
    s = re.sub(r"(?i)\bwhat\s*is\s*it\s*formulated\s*to\s*do\s*:?", " ", s)

    # Fix missing spaces between lower->upper and after punctuation
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)
    s = re.sub(r"(?<=[.!?])(?=[A-Za-z])", " ", s)

    # Normalize whitespace
    s = re.sub(r"\s+", " ", s).strip()
    return s


def trim_to_this_sentence(description):
    if pd.isna(description):
        return ""
    text = str(description).strip()
    if not text:
        return ""

    sentences = re.split(r"(?<=[.!?])\s+", text)
    for i, sentence in enumerate(sentences):
        if re.match(r"(?i)^\s*this\b", sentence):
            return " ".join(sentences[i:]).strip()
    return text

# Ensure category uses spaces, not dashes
if "category" in df.columns:
    df["category"] = df["category"].fillna("").astype(str).str.replace("-", " ", regex=False).str.strip()

# Keep your broader category cleanup if desired
for col in ["primary_category", "secondary_category", "tertiary_category"]:
    if col in df.columns:
        df[col] = df[col].fillna("").astype(str).str.replace("-", " ", regex=False).str.strip()

if "highlights" in df.columns:
    df["highlights"] = df["highlights"].apply(clean_list_like_text)

if "ingredients" in df.columns:
    df["ingredients"] = df["ingredients"].apply(clean_list_like_text)

if "description" in df.columns:
    df["description"] = df["description"].apply(clean_description)

# Product-specific fix: ensure this description starts with the first "This..." sentence.
if "description" in df.columns and "product_name" in df.columns:
    supergoop_mask = df["product_name"].astype(str).str.contains(
        r"every\.\s*single\.\s*face\..*lotion",
        case=False,
        na=False,
        regex=True,
    )
    if "brand_name" in df.columns:
        supergoop_mask &= df["brand_name"].astype(str).str.contains(r"supergoop", case=False, na=False)
    elif "brand" in df.columns:
        supergoop_mask &= df["brand"].astype(str).str.contains(r"supergoop", case=False, na=False)

    df.loc[supergoop_mask, "description"] = df.loc[supergoop_mask, "description"].apply(trim_to_this_sentence)

# Extra pass for JACK BLACK descriptions (if brand column exists)
brand_col = next((c for c in ["brand", "brand_name", "brandName"] if c in df.columns), None)
if brand_col and "description" in df.columns:
    jack_black_mask = df[brand_col].astype(str).str.contains(r"\bjack\s*black\b", case=False, na=False)
    df.loc[jack_black_mask, "description"] = df.loc[jack_black_mask, "description"].apply(clean_description)

# Keep all categories (including perfume and hair products).

# Backup then overwrite
if not os.path.exists(backup_path):
    pd.read_csv(csv_path).to_csv(backup_path, index=False)

df.to_csv(csv_path, index=False)

# print(f"Rows before: {before}, after filtering: {after}")

# if "secondary_category" in df.columns:
#     # secondary categories with fewer than 20 products
#     secondary_counts = df["secondary_category"].fillna("MISSING").value_counts()
#     rare_secondary = secondary_counts[secondary_counts < 20].index

#     # choose product-name column safely
#     product_col = "product_name" if "product_name" in df.columns else ("name" if "name" in df.columns else None)

#     cols_to_show = [c for c in [product_col, "primary_category", "secondary_category"] if c is not None and c in df.columns]
#     rare_rows = df[df["secondary_category"].fillna("MISSING").isin(rare_secondary)][cols_to_show]

#     print("\nProducts + primary_category where secondary_category count < 20:")
#     print(rare_rows.sort_values(by=["secondary_category", "primary_category"]).to_string(index=False))

# for col in ["primary_category", "category", "secondary_category"]:
#     if col in df.columns:
#         counts = df[col].fillna("MISSING").astype(str).str.strip()
#         counts = counts.replace("", "MISSING").value_counts()

#         print(f"\nDistinct {col} values with quantity:")
#         print(counts.to_string())
#     else:
#         print(f"\nColumn not found: {col}")

# Preprocess skin condition CSV to ensure consistent formatting
df = pd.read_csv('ingredients_skin_conditions.csv')
df['Good_Ingredients'] = df['Good_Ingredients'].str.lower()
df['Bad_Ingredients'] = df['Bad_Ingredients'].str.lower()
df.to_csv('ingredients_skin_conditions.csv', index=False)

