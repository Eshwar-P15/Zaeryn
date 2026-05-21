import sys
import os
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import nltk
for corpus in ["punkt", "punkt_tab"]:
    try:
        nltk.data.find(f"tokenizers/{corpus}")
    except LookupError:
        print(f"Downloading NLTK data: {corpus}...")
        nltk.download(corpus, quiet=True)

from config.settings import ALL_ASSETS, SOLANA_TOKENS
from utils.logger import get_logger
from sentiment.fear_greed    import fetch_fear_greed
from sentiment.dex_sentiment import fetch_dex_sentiment
from sentiment.onchain       import fetch_onchain_sentiment
from sentiment.news          import fetch_news_sentiment
from sentiment.scorer        import compute_sentiment_score, score_all_assets

logger = get_logger("run_sentiment")


def main():
    print("\n" + "="*70)
    print("  ZAERYN - Phase 2 Sentiment Engine Validation")
    print("="*70 + "\n")

    # --- 1. Fear & Greed ---
    print("[ 1 / 5 ] Fear & Greed Index...")
    fg = fetch_fear_greed()
    status = "OK" if "error" not in fg else "WARN"
    print(f"          {status}  {fg['value']}/100 | {fg['label']} | normalized={fg['normalized']:+.3f}\n")

    # --- 2. DEX sentiment ---
    print(f"[ 2 / 5 ] DEX buy/sell ratios (Solana tokens)...\n")
    for asset in SOLANA_TOKENS:
        dx = fetch_dex_sentiment(asset)
        ok = "OK  " if dx.get("confidence", 0) > 0 else "SKIP"
        print(
            f"  {ok} {asset:<10} "
            f"score={dx['score']:+.3f}  "
            f"buys={dx.get('buys_1h', 'N/A')}  "
            f"sells={dx.get('sells_1h', 'N/A')}  "
            f"ratio={dx.get('ratio_1h', 0):.2f}"
        )

    # --- 3. On-chain ---
    print(f"\n[ 3 / 5 ] Helius on-chain signals (Solana tokens)...\n")
    for asset in SOLANA_TOKENS:
        oc = fetch_onchain_sentiment(asset)
        ok = "OK  " if oc.get("confidence", 0) > 0 else "SKIP"
        print(
            f"  {ok} {asset:<10} "
            f"score={oc['score']:+.3f}  "
            f"whale_conc={oc.get('whale_concentration', 0):.1f}%  "
            f"holders={oc.get('holder_count', 0)}"
        )

    # --- 4. News ---
    print(f"\n[ 4 / 5 ] NewsAPI headlines (first 3 assets)...\n")
    for asset in ALL_ASSETS[:3]:
        nw = fetch_news_sentiment(asset)
        ok = "OK  " if nw.get("confidence", 0) > 0 else "SKIP"
        print(
            f"  {ok} {asset:<12} "
            f"score={nw['score']:+.3f}  "
            f"articles={nw.get('article_count', 0)}  "
            f"conf={nw.get('confidence', 0):.2f}"
        )

    # --- 5. Full composite ---
    print(f"\n[ 5 / 5 ] Full composite scores (Twitter disabled)...\n")
    print(f"  {'Asset':<12} {'Score':>8}  {'Label':<15}  {'Conf':>6}  Components")
    print("  " + "-"*78)

    results = score_all_assets(include_twitter=False)
    for asset, result in results.items():
        comps = result.get("components", {})
        comp_str = "  ".join(
            f"{src[:3]}={detail['score']:+.2f}"
            for src, detail in comps.items()
            if detail.get("base_weight", 0) > 0
        )
        print(
            f"  {asset:<12} "
            f"{result['score']:>+8.4f}  "
            f"{result['label']:<15}  "
            f"{result['confidence']:>6.2f}  "
            f"{comp_str}"
        )

    print()
    print("="*70)
    print("  Phase 2 validation complete!")
    print()
    print("  To test Twitter (when credentials confirmed):")
    print("  python -c \"from sentiment.twitter_scraper import fetch_twitter_sentiment; print(fetch_twitter_sentiment('SOL-USD'))\"")
    print()
    print("  Ready to commit:")
    print("  git add . && git commit -m 'v0.2.0-sentiment-engine'")
    print("="*70 + "\n")


if __name__ == "__main__":
    main()
