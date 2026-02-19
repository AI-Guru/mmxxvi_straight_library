"""CLI to upload all _libraryentry.md files to the Straight Library API."""

import argparse
import glob
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


def upload_file(api_url: str, filepath: str) -> dict:
    """Upload a single _libraryentry.md file to the API."""
    with open(filepath, "rb") as f:
        response = requests.post(
            f"{api_url}/api/upload",
            files={"file": (os.path.basename(filepath), f, "text/markdown")},
        )
    response.raise_for_status()
    return response.json()


def main():
    parser = argparse.ArgumentParser(
        description="Upload _libraryentry.md files to the Straight Library API"
    )
    parser.add_argument(
        "--api-url",
        default="http://localhost:9821",
        help="API base URL (default: http://localhost:9821)",
    )
    parser.add_argument(
        "--data-dir",
        default="data",
        help="Data directory to search for _libraryentry.md files (default: data)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of concurrent upload workers (default: 4)",
    )
    args = parser.parse_args()

    files = sorted(
        glob.glob(os.path.join(args.data_dir, "**", "*_libraryentry.md"), recursive=True)
    )
    if not files:
        print(f"No _libraryentry.md files found in {args.data_dir}")
        sys.exit(1)

    print(f"Found {len(files)} library entry files. Uploading to {args.api_url}...")

    success = 0
    failed = 0

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(upload_file, args.api_url, f): f for f in files
        }
        for i, future in enumerate(as_completed(futures), 1):
            filepath = futures[future]
            try:
                result = future.result()
                print(f"  [{i}/{len(files)}] {result['title']} ({result['entry_id']})")
                success += 1
            except Exception as e:
                print(f"  [{i}/{len(files)}] FAILED {os.path.basename(filepath)}: {e}")
                failed += 1

    print(f"\nDone. Uploaded: {success}, Failed: {failed}")


if __name__ == "__main__":
    main()
