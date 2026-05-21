import time

import requests

from config.settings import (
    DEXSCREENER_BASE_URL,
    MIN_LIQUIDITY_USD,
    MIN_VOLUME_24H_USD,
    REQUEST_RETRY_ATTEMPTS,
    REQUEST_RETRY_DELAYS,
    REQUEST_TIMEOUT,
    SOLANA_TOKENS,
)
from utils.logger import get_logger

logger = get_logger(__name__)

_pair_address_cache: dict[str, str] = {}


def _get(url: str, params: dict = None) -> dict:
    last_error = None
    for attempt in range(REQUEST_RETRY_ATTEMPTS):
        if attempt > 0:
            wait = REQUEST_RETRY_DELAYS[attempt - 1]
            logger.debug(f"Retry {attempt} for {url}, waiting {wait}s")
            time.sleep(wait)
        try:
            response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            last_error = e
            logger.warning(f"DexScreener request failed (attempt {attempt + 1}): {e}")
    raise RuntimeError(f"All retries exhausted for {url}. Last error: {last_error}")


def _select_best_pair(pairs: list[dict], symbol: str) -> dict | None:
    solana_pairs = [p for p in pairs if p.get("chainId") == "solana"]

    if not solana_pairs:
        logger.warning(f"No Solana pairs found for {symbol}")
        return None

    qualifying = []
    for pair in solana_pairs:
        liquidity = pair.get("liquidity", {}).get("usd", 0) or 0
        volume_24h = pair.get("volume", {}).get("h24", 0) or 0
        if liquidity >= MIN_LIQUIDITY_USD and volume_24h >= MIN_VOLUME_24H_USD:
            qualifying.append(pair)

    if not qualifying:
        logger.warning(
            f"No qualifying pairs for {symbol} "
            f"(min liquidity: ${MIN_LIQUIDITY_USD:,}, min volume: ${MIN_VOLUME_24H_USD:,})"
        )
        solana_pairs.sort(key=lambda p: p.get("liquidity", {}).get("usd", 0) or 0, reverse=True)
        best = solana_pairs[0]
        best["_below_threshold"] = True
        return best

    qualifying.sort(key=lambda p: p.get("liquidity", {}).get("usd", 0) or 0, reverse=True)
    return qualifying[0]


def fetch_token_info(symbol: str) -> dict | None:
    if symbol not in SOLANA_TOKENS:
        raise ValueError(
            f"Unknown symbol '{symbol}'. Add it to SOLANA_TOKENS in config/settings.py"
        )

    mint_address = SOLANA_TOKENS[symbol]
    url = f"{DEXSCREENER_BASE_URL}/tokens/{mint_address}"

    try:
        data = _get(url)
    except RuntimeError as e:
        logger.error(f"fetch_token_info failed for {symbol}: {e}")
        return None

    pairs = data.get("pairs") or []
    if not pairs:
        logger.warning(f"No pairs returned for {symbol} ({mint_address})")
        return None

    best_pair = _select_best_pair(pairs, symbol)
    if best_pair is None:
        return None

    base_token = best_pair.get("baseToken", {})
    price_str = best_pair.get("priceUsd", "0") or "0"

    info = {
        "symbol": symbol,
        "name": base_token.get("name", symbol),
        "mint_address": mint_address,
        "pair_address": best_pair.get("pairAddress", ""),
        "dex": best_pair.get("dexId", "unknown"),
        "price_usd": float(price_str),
        "price_change_24h": best_pair.get("priceChange", {}).get("h24", 0.0) or 0.0,
        "volume_24h": best_pair.get("volume", {}).get("h24", 0.0) or 0.0,
        "liquidity_usd": best_pair.get("liquidity", {}).get("usd", 0.0) or 0.0,
        "market_cap": best_pair.get("marketCap", 0.0) or 0.0,
        "below_threshold": best_pair.get("_below_threshold", False),
    }

    if info["below_threshold"]:
        logger.warning(
            f"{symbol} is below liquidity/volume thresholds - price data may be unreliable. "
            f"Liquidity: ${info['liquidity_usd']:,.0f}, Volume 24h: ${info['volume_24h']:,.0f}"
        )

    logger.debug(f"fetch_token_info: {symbol} @ ${info['price_usd']:.6f} (DEX: {info['dex']})")
    return info


def fetch_dex_price(symbol: str) -> float | None:
    info = fetch_token_info(symbol)
    if info is None:
        return None
    return info["price_usd"]


def fetch_all_dex_prices() -> dict[str, float]:
    prices = {}
    for symbol in SOLANA_TOKENS:
        try:
            price = fetch_dex_price(symbol)
            if price is not None and price > 0:
                prices[symbol] = price
                logger.info(f"  {symbol}: ${price:.8f}")
            else:
                logger.warning(f"  {symbol}: price unavailable")
        except Exception as e:
            logger.error(f"  {symbol}: failed - {e}")
        time.sleep(0.2)
    return prices


def get_pair_address(symbol: str) -> str | None:
    if symbol in _pair_address_cache:
        return _pair_address_cache[symbol]

    info = fetch_token_info(symbol)
    if info is None:
        return None

    pair_address = info["pair_address"]
    _pair_address_cache[symbol] = pair_address
    return pair_address


def search_token(query: str) -> list[dict]:
    url = f"{DEXSCREENER_BASE_URL}/search"
    params = {"q": query}

    try:
        data = _get(url, params=params)
    except RuntimeError as e:
        logger.error(f"search_token failed for '{query}': {e}")
        return []

    pairs = data.get("pairs") or []
    results = []
    for pair in pairs[:10]:
        base = pair.get("baseToken", {})
        results.append(
            {
                "symbol": base.get("symbol", ""),
                "name": base.get("name", ""),
                "chain": pair.get("chainId", ""),
                "price_usd": float(pair.get("priceUsd", 0) or 0),
                "volume_24h": pair.get("volume", {}).get("h24", 0) or 0,
                "liquidity_usd": pair.get("liquidity", {}).get("usd", 0) or 0,
                "pair_address": pair.get("pairAddress", ""),
                "dex": pair.get("dexId", ""),
            }
        )
    return results
