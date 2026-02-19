import glob
import json
import os

import yaml

DATA_DIR = "data"

metadata_files = glob.glob(os.path.join(DATA_DIR, "**", "*_metadata.json"), recursive=True)
metadata_files.sort()

print(f"Found {len(metadata_files)} metadata files.")

# Build tuples of (metadata, shortsummary, summary, full) for each book.
book_tuples = []
for metadata_file in metadata_files:
    base = metadata_file.replace("_metadata.json", "")
    book_tuple = (
        metadata_file,
        base + "_shortsummary.md",
        base + "_summary.md",
        base + ".md",
    )
    book_tuples.append(book_tuple)

print(f"Found {len(book_tuples)} book tuples.")

# Build library entries in memory and assert correct structure.
library_entries = []
for metadata_path, shortsummary_path, summary_path, full_path in book_tuples:
    with open(metadata_path, "r") as f:
        metadata = json.load(f)
    metadata_yaml = yaml.dump(metadata, default_flow_style=False, allow_unicode=True).strip()

    def read_and_clean(path):
        with open(path, "r") as f:
            lines = f.read().strip().split("\n")
        return "\n".join(line for line in lines if line.strip() != "---")

    shortsummary = read_and_clean(shortsummary_path)
    summary = read_and_clean(summary_path)
    fulltext = read_and_clean(full_path)

    entry = f"---\n{metadata_yaml}\n---\n{shortsummary}\n---\n{summary}\n---\n{fulltext}"

    # Assert exactly 4 "---" separator lines.
    separator_count = sum(1 for line in entry.split("\n") if line.strip() == "---")
    assert separator_count == 4, (
        f"Expected 4 separators, got {separator_count} in {metadata_path}"
    )

    # Write the library entry file.
    entry_path = metadata_path.replace("_metadata.json", "_libraryentry.md")
    with open(entry_path, "w") as f:
        f.write(entry + "\n")

    library_entries.append(entry)

print(f"Wrote {len(library_entries)} library entry files.")
