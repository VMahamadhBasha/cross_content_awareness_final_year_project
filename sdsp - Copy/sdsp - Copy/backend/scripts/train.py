"""Train the engagement forecaster on real SMPD data and print evaluation metrics."""
import argparse
import json

from app.config import get_settings
from app.forecasting.model import EngagementForecaster
from app.forecasting.service import MODEL_FILE
from app.forecasting.training import evaluate_cross_platform, evaluate_in_platform


def main() -> None:
    """Parse arguments, evaluate, train on real rows and save the model."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--posts-csv", required=True, help="SMPD posts CSV")
    ap.add_argument("--label-file", help="optional SMPD label file with one popularity score per row")
    ap.add_argument("--kind", choices=["image", "video"], default="image")
    ap.add_argument("--column-map", default="{}", help='JSON overriding column names, e.g. {"user":"Uid","caption":"Title","tags":"Alltags","time":"Postdate","label":"label"}')
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    from app.forecasting.smpd import load_smpd

    rows, y = load_smpd(args.posts_csv, args.label_file, args.kind, json.loads(args.column_map), args.limit)
    print(f"rows: {len(rows)}")
    print("in-platform holdout:", json.dumps(evaluate_in_platform(rows, y), indent=2))
    cross = evaluate_cross_platform(rows, y)
    if cross:
        print("leave-one-platform-out:", json.dumps(cross, indent=2))
    path = get_settings().model_dir / MODEL_FILE
    EngagementForecaster().fit(rows, y).save(path)
    print(f"saved {path}")


if __name__ == "__main__":
    main()
