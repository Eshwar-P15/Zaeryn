import os
import time

import requests

from config.settings import (
    ASSET_SOURCE,
    HELIUS_BASE_URL,
    REQUEST_RETRY_ATTEMPTS,
    REQUEST_RETRY_DELAYS,
    REQUEST_TIMEOUT,
    SOLANA_TOKENS,
)
from utils.logger import get_logger

logger = get_logger(__name__)


def _helius_post(payload: dict) -> dict:
    api_key = os.getenv("HELIUS_API_KEY", "")
    if not api_key:
        raise ValueError("HELIUS_API_KEY not set")

    url = f"{HELIUS_BASE_URL}/?api-key={api_key}"
    last_error = None
    for attempt in range(REQUEST_RETRY_ATTEMPTS):
        if attempt > 0:
            time.sleep(REQUEST_RETRY_DELAYS[attempt - 1])
        try:
            response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            last_error = e
            safe_msg = str(e).replace(api_key, "***")
            logger.warning(f"Helius RPC failed (attempt {attempt + 1}): {safe_msg}")
    raise RuntimeError(f"Helius RPC all retries failed: {str(last_error).replace(api_key, '***')}")


def fetch_token_holders(mint_address: str, limit: int = 20) -> list[dict]:
    payload = {
        "jsonrpc": "2.0",
        "id": "zaeryn-holders",
        "method": "getTokenLargestAccounts",
        "params": [mint_address],
    }
    try:
        result = _helius_post(payload)
        accounts = result.get("result", {}).get("value", [])
        return accounts[:limit]
    except Exception as e:
        logger.warning(f"getTokenLargestAccounts failed for {mint_address}: {e}")
        return []


def fetch_token_supply(mint_address: str) -> float:
    payload = {
        "jsonrpc": "2.0",
        "id": "zaeryn-supply",
        "method": "getTokenSupply",
        "params": [mint_address],
    }
    try:
        result = _helius_post(payload)
        value = result.get("result", {}).get("value", {})
        return float(value.get("uiAmount", 0) or 0)
    except Exception as e:
        logger.warning(f"getTokenSupply failed for {mint_address}: {e}")
        return 0.0


def compute_whale_concentration(holders: list[dict], total_supply: float) -> float:
    """
    Computes % of supply held by top N holders.

    Handles uiAmount=None by falling back to amount + decimals arithmetic.
    """
    if not holders or total_supply <= 0:
        return 0.0

    def safe_ui_amount(h: dict) -> float:
        ui = h.get("uiAmount")
        if ui is not None:
            return float(ui)
        try:
            raw = int(h.get("amount", 0) or 0)
            decimals = int(h.get("decimals", 0) or 0)
            return raw / (10**decimals) if decimals >= 0 else float(raw)
        except Exception:
            return 0.0

    top_holdings = sum(safe_ui_amount(h) for h in holders)
    return round((top_holdings / total_supply) * 100, 2)


def fetch_onchain_sentiment(asset: str) -> dict:
    """
    On-chain sentiment for Solana DEX tokens via Helius.

    Scoring driven by whale concentration:
        < 20%: +0.3 (healthy distribution)
        20-40%: 0.0 (neutral)
        40-60%: -0.3 (concentrated)
        > 60%: -0.6 (extreme concentration / whale dump risk)

    Coinbase / stock / forex assets always return neutral. Solana tokens
    route via `"birdeye"` (post Phase 1.5) — they must still flow through
    the Helius path. See docs/repo_audit.md §8.
    """
    if ASSET_SOURCE.get(asset) not in ("dex", "birdeye"):
        return {
            "score": 0.0,
            "confidence": 0.0,
            "source": "onchain",
            "asset": asset,
            "note": "non-solana asset - no on-chain analysis",
        }

    mint_address = SOLANA_TOKENS.get(asset)
    if not mint_address:
        return _null_result(asset, "no mint address")

    if not os.getenv("HELIUS_API_KEY", ""):
        logger.warning("HELIUS_API_KEY not set - skipping on-chain sentiment")
        return _null_result(asset, "no API key")

    try:
        holders = fetch_token_holders(mint_address, limit=20)
        total_supply = fetch_token_supply(mint_address)
        holder_count = len(holders)
        whale_pct = compute_whale_concentration(holders, total_supply)

        if whale_pct < 20:
            whale_score = 0.3
        elif whale_pct < 40:
            whale_score = 0.0
        elif whale_pct < 60:
            whale_score = -0.3
        else:
            whale_score = -0.6

        final_score = max(-1.0, min(1.0, whale_score))
        confidence = 0.8 if holder_count >= 5 else 0.3

        result = {
            "score": round(final_score, 4),
            "whale_concentration": whale_pct,
            "holder_count": holder_count,
            "total_supply": total_supply,
            "confidence": confidence,
            "source": "onchain",
            "asset": asset,
        }
        logger.info(
            f"On-chain {asset}: {final_score:+.3f} "
            f"(whale_conc={whale_pct:.1f}%, holders={holder_count})"
        )
        return result

    except Exception as e:
        logger.error(f"On-chain sentiment failed for {asset}: {e}")
        return _null_result(asset, str(e))


def _null_result(asset: str, reason: str = "") -> dict:
    return {"score": 0.0, "confidence": 0.0, "source": "onchain", "asset": asset, "error": reason}
