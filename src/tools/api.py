import datetime
import logging
import os
import pandas as pd
import requests
import threading
import time
import yfinance as yf

logger = logging.getLogger(__name__)

from src.data.cache import get_cache
from src.data.models import (
    CompanyNews,
    CompanyNewsResponse,
    FinancialMetrics,
    FinancialMetricsResponse,
    Price,
    PriceResponse,
    LineItem,
    LineItemResponse,
    InsiderTrade,
    InsiderTradeResponse,
    CompanyFactsResponse,
)

# Global cache instance
_cache = get_cache()

lock_make_api_request = threading.Lock()
lock_get_prices = threading.Lock()
lock_get_financial_metrics = threading.Lock()
lock_search_line_items = threading.Lock()
lock_get_insider_trades = threading.Lock()
lock_get_company_news = threading.Lock()
lock_get_market_cap = threading.Lock()

def record(url: str, logfile: str = "api.log"):
    """Append a URL call with timestamp to the log file."""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d")
    with open(logfile, "a", encoding="utf-8") as f:
        f.write(f"{timestamp} - {url}\n")

def _make_api_request(url: str, headers: dict, method: str = "GET", json_data: dict = None, max_retries: int = 3) -> requests.Response:
    """
    Make an API request with rate limiting handling and moderate backoff.
    
    Args:
        url: The URL to request
        headers: Headers to include in the request
        method: HTTP method (GET or POST)
        json_data: JSON data for POST requests
        max_retries: Maximum number of retries (default: 3)
    
    Returns:
        requests.Response: The response object
    
    Raises:
        Exception: If the request fails with a non-429 error
    """
    with lock_make_api_request:
        time.sleep(1)
        record(url)
        for attempt in range(max_retries + 1):  # +1 for initial attempt
            if method.upper() == "POST":
                response = requests.post(url, headers=headers, json=json_data)
            else:
                response = requests.get(url, headers=headers)
            
            if response.status_code == 429 and attempt < max_retries:
                # Linear backoff: 60s, 90s, 120s, 150s...
                delay = 60 + (30 * attempt)
                print(f"Rate limited (429). Attempt {attempt + 1}/{max_retries + 1}. Waiting {delay}s before retrying...")
                time.sleep(delay)
                continue
            
            # Return the response (whether success, other errors, or final 429)
            return response


def get_prices(ticker: str, start_date: str, end_date: str, api_key: str = None) -> list[Price]:
    """Fetch price data from cache or API."""
    with lock_get_prices:
        # Create a cache key that includes all parameters to ensure exact matches
        cache_key = f"{ticker}_{start_date}_{end_date}"
        
        # Check cache first - simple exact match
        if cached_data := _cache.get_prices(cache_key):
            return [Price(**price) for price in cached_data]

        # If not in cache, fetch from API
        headers = {}
        financial_api_key = api_key or os.environ.get("FINANCIAL_DATASETS_API_KEY")
        if financial_api_key:
            headers["X-API-KEY"] = financial_api_key

        url = f"https://api.financialdatasets.ai/prices/?ticker={ticker}&interval=day&interval_multiplier=1&start_date={start_date}&end_date={end_date}"
        response = _make_api_request(url, headers)
        if response.status_code != 200:
            return []

        # Parse response with Pydantic model
        try:
            price_response = PriceResponse(**response.json())
            prices = price_response.prices
        except Exception as e:
            logger.warning("Failed to parse price response for %s: %s", ticker, e)
            return []

        if not prices:
            return []

        # Cache the results using the comprehensive cache key
        _cache.set_prices(cache_key, [p.model_dump() for p in prices])
        return prices


def get_financial_metrics(
    ticker: str,
    end_date: str,
    period: str = "ttm",
    limit: int = 10,
    api_key: str = None,
) -> list[FinancialMetrics]:
    """Fetch financial metrics from cache or API."""
    with lock_get_financial_metrics:
        # Create a cache key that includes all parameters to ensure exact matches
        cache_key = f"{ticker}_{period}_{limit}"
        
        # Check cache first - simple exact match
        if cached_data := _cache.get_financial_metrics(cache_key):
            return [FinancialMetrics(**metric) for metric in cached_data]

        # If not in cache, fetch from API
        headers = {}
        financial_api_key = api_key or os.environ.get("FINANCIAL_DATASETS_API_KEY")
        if financial_api_key:
            headers["X-API-KEY"] = financial_api_key

        url = f"https://api.financialdatasets.ai/financial-metrics/?ticker={ticker}&report_period_lte={end_date}&limit={limit}&period={period}"
        response = _make_api_request(url, headers)
        if response.status_code != 200:
            return []

        # Parse response with Pydantic model
        try:
            metrics_response = FinancialMetricsResponse(**response.json())
            financial_metrics = metrics_response.financial_metrics
        except Exception as e:
            logger.warning("Failed to parse financial metrics response for %s: %s", ticker, e)
            return []

        if not financial_metrics:
            return []

        # Cache the results as dicts using the comprehensive cache key
        _cache.set_financial_metrics(cache_key, [m.model_dump() for m in financial_metrics])
        return financial_metrics


def search_line_items(
    ticker: str,
    line_items: list[str],
    end_date: str,
    period: str = "ttm",
    limit: int = 10,
    api_key: str = None,
) -> list[LineItem]:
    """Fetch line items from API."""
    with lock_search_line_items:
        # Create a cache key that includes all parameters to ensure exact matches
        cache_key = f"{ticker}_{period}_{limit}"
        
        # Check cache first - simple exact match
        if cached_data := _cache.get_line_items(cache_key):
            return [LineItem(**metric) for metric in cached_data]

        # If not in cache or insufficient data, fetch from API
        headers = {}
        financial_api_key = api_key or os.environ.get("FINANCIAL_DATASETS_API_KEY")
        if financial_api_key:
            headers["X-API-KEY"] = financial_api_key

        url = "https://api.financialdatasets.ai/financials/search/line-items"

        body = {
            "tickers": [ticker],
            "line_items": line_items,
            "end_date": end_date,
            "period": period,
            "limit": limit,
        }
        response = _make_api_request(url, headers, method="POST", json_data=body)
        if response.status_code != 200:
            return []
    
        try:
            data = response.json()
            response_model = LineItemResponse(**data)
            search_results = response_model.search_results
        except Exception as e:
            logger.warning("Failed to parse line items response for %s: %s", ticker, e)
            return []
        if not search_results:
            return []

        # Cache the results as dicts using the comprehensive cache key
        _cache.set_line_items(cache_key, [result.model_dump() for result in search_results])
        return search_results[:limit]


def get_insider_trades(
    ticker: str,
    end_date: str,
    start_date: str | None = None,
    limit: int = 1000,
    api_key: str = None,
) -> list[InsiderTrade]:
    """Fetch insider trades from cache or API."""
    with lock_get_insider_trades:
        # Create a cache key that includes all parameters to ensure exact matches
        cache_key = f"{ticker}_{end_date[:7]}"
        
        # Check cache first - simple exact match
        if cached_data := _cache.get_insider_trades(cache_key):
            return [InsiderTrade(**trade) for trade in cached_data][:limit]

        # If not in cache, fetch from API
        headers = {}
        financial_api_key = api_key or os.environ.get("FINANCIAL_DATASETS_API_KEY")
        if financial_api_key:
            headers["X-API-KEY"] = financial_api_key

        all_trades = []
        current_end_date = end_date

        while True:
            url = f"https://api.financialdatasets.ai/insider-trades/?ticker={ticker}&filing_date_lte={current_end_date}"
            if start_date:
                url += f"&filing_date_gte={start_date}"
            url += f"&limit=50"

            response = _make_api_request(url, headers)
            if response.status_code != 200:
                break

            try:
                data = response.json()
                response_model = InsiderTradeResponse(**data)
                insider_trades = response_model.insider_trades
            except Exception as e:
                logger.warning("Failed to parse insider trades response for %s: %s", ticker, e)
                break

            if not insider_trades:
                break

            all_trades.extend(insider_trades)

            # Only continue pagination if we have a start_date and got a full page
            if not start_date or len(insider_trades) < 1000:
                break

            # Update end_date to the oldest filing date from current batch for next iteration
            current_end_date = min(trade.filing_date for trade in insider_trades).split("T")[0]

            # If we've reached or passed the start_date, we can stop
            if current_end_date <= start_date:
                break

        if not all_trades:
            return []

        # Cache the results using the comprehensive cache key
        _cache.set_insider_trades(cache_key, [trade.model_dump() for trade in all_trades])
    return get_insider_trades(ticker=ticker, end_date=end_date, start_date=start_date, limit=limit, api_key=api_key)


def get_company_news(
    ticker: str,
    limit: int = 10,
    api_key: str = None,
) -> list[CompanyNews]:
    """Fetch company news from cache or API."""
    with lock_get_company_news:
        cache_key = ticker

        # Check cache first
        if cached_data := _cache.get_company_news(cache_key):
            return [CompanyNews(**news) for news in cached_data][:limit]

        # If not in cache, fetch from API
        headers = {}
        financial_api_key = api_key or os.environ.get("FINANCIAL_DATASETS_API_KEY")
        if financial_api_key:
            headers["X-API-KEY"] = financial_api_key

        url = f"https://api.financialdatasets.ai/news?ticker={ticker}&limit={limit}"

        response = _make_api_request(url, headers)
        if response.status_code != 200:
            return []

        try:
            data = response.json()
            response_model = CompanyNewsResponse(**data)
            all_news = response_model.news
        except Exception as e:
            logger.warning("Failed to parse company news response for %s: %s", ticker, e)
            return []

        if not all_news:
            return []

        # Cache the results
        _cache.set_company_news(cache_key, [news.model_dump() for news in all_news])
    return get_company_news(ticker=ticker, limit=limit, api_key=api_key)


def get_market_cap(
    ticker: str,
    end_date: str,
    api_key: str = None,
) -> float | None:
    """Fetch market cap from the API."""
    with lock_get_market_cap:
        return yf.Ticker(ticker).info.get("marketCap")


def prices_to_df(prices: list[Price]) -> pd.DataFrame:
    """Convert prices to a DataFrame."""
    df = pd.DataFrame([p.model_dump() for p in prices])
    df["Date"] = pd.to_datetime(df["time"])
    df.set_index("Date", inplace=True)
    numeric_cols = ["open", "close", "high", "low", "volume"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df.sort_index(inplace=True)
    return df


# Update the get_price_data function to use the new functions
def get_price_data(ticker: str, start_date: str, end_date: str, api_key: str = None) -> pd.DataFrame:
    prices = get_prices(ticker, start_date, end_date, api_key=api_key)
    return prices_to_df(prices)