"""Read-only adapters. Broker execution endpoints deliberately do not exist."""

from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
from urllib.parse import urlencode
from .http_client import request_json
from .models import Candle, SECONDS, ValidationError, iso, now_utc, number, pair_name, utc


def read_json(path: str | Path) -> dict:
    raw = Path(path).read_text(encoding="utf-8")
    if len(raw) > 10 * 1024 * 1024:
        raise ValidationError("File JSON terlalu besar.")
    try:
        result = json.loads(raw, parse_constant=lambda x: (_ for _ in ()).throw(ValidationError(f"JSON {x} tidak valid.")))
    except json.JSONDecodeError as exc:
        raise ValidationError(f"JSON tidak valid pada baris {exc.lineno}.") from None
    if not isinstance(result, dict):
        raise ValidationError("Dokumen JSON harus object.")
    return result


def csv_snapshot(folder: str, metadata: dict) -> dict:
    """CSV timestamps must already be close times with UTC offsets."""
    out = dict(metadata)
    out["frames"] = {}
    for tf in SECONDS:
        path = Path(folder) / f"{tf}.csv"
        if not path.exists():
            continue
        with path.open(encoding="utf-8", newline="") as file:
            values = []
            for row in csv.DictReader(file):
                if "complete" in row:
                    if row["complete"].lower() not in ("true", "false"):
                        raise ValidationError("Kolom complete CSV harus true/false.")
                    if row["complete"].lower() == "false":
                        continue
                    row["complete"] = True
                candle = Candle.parse(row)
                values.append({"time": iso(candle.time), "open": candle.open, "high": candle.high,
                               "low": candle.low, "close": candle.close, "volume": candle.volume})
                if len(values) > 5000:
                    raise ValidationError("CSV dibatasi 5000 candle per timeframe.")
            out["frames"][tf] = values
    out["source"] = "CSV user-supplied (" + str(metadata.get("source", "unspecified")) + ")"
    return out


class OandaProvider:
    def __init__(self, *, token: str | None = None, account_id: str | None = None,
                 environment: str = "practice", transport=request_json):
        self.token = token or os.getenv("OANDA_API_TOKEN", "")
        self.account = account_id or os.getenv("OANDA_ACCOUNT_ID", "")
        if not self.token or not re.fullmatch(r"[A-Za-z0-9-]+", self.account):
            raise ValidationError("OANDA_API_TOKEN dan OANDA_ACCOUNT_ID yang valid diperlukan.")
        if environment not in ("practice", "live"):
            raise ValidationError("Environment harus practice/live.")
        self.base = "https://api-fxpractice.oanda.com" if environment == "practice" else "https://api-fxtrade.oanda.com"
        self.environment = environment
        self.transport = transport

    def _get(self, path, params=None):
        suffix = "?" + urlencode(params) if params else ""
        return self.transport(self.base + path + suffix, headers={"Authorization": f"Bearer {self.token}"})

    def snapshot(self, pair: str, *, contract_size: float, day_start_equity: float,
                 fundamentals: dict, count: int = 350) -> dict:
        pair = pair_name(pair)
        if not 250 <= count <= 5000:
            raise ValidationError("count harus 250–5000.")
        symbol = pair.replace("/", "_")
        root = f"/v3/accounts/{self.account}"
        instruments = self._get(root + "/instruments", {"instruments": symbol})["instruments"]
        matches = [s for s in instruments if s["name"] == symbol]
        if not matches:
            raise ValidationError("Instrumen tidak tersedia untuk akun/divisi broker ini.")
        s = matches[0]
        account = self._get(root + "/summary")["account"]
        account_stamp = now_utc()
        frames = {}
        for tf, seconds in SECONDS.items():
            response = self._get(root + f"/instruments/{symbol}/candles", {
                "granularity": "D" if tf == "Daily" else tf, "price": "M", "count": count,
                "dailyAlignment": 0, "alignmentTimezone": "UTC", "smooth": "false"})
            frames[tf] = [{"time": iso(utc(c["time"]) + timedelta(seconds=seconds)),
                           **{dest: float(c["mid"][src]) for dest, src in
                              (("open", "o"), ("high", "h"), ("low", "l"), ("close", "c"))},
                           "volume": c["volume"], "complete": True}
                          for c in response["candles"] if c["complete"] is True]
        pricing = self._get(root + "/pricing", {"instruments": symbol, "includeHomeConversions": "true"})
        quotes = [p for p in pricing["prices"] if p["instrument"] == symbol]
        if not quotes or not quotes[0]["bids"] or not quotes[0]["asks"]:
            raise ValidationError("Quote bid/ask tidak tersedia.")
        quote = quotes[0]
        quote_currency = pair.split("/")[1]
        if quote_currency == account["currency"]:
            factors = {"accountLoss": 1, "accountGain": 1, "positionValue": 1}
        else:
            factors = next((c for c in pricing.get("homeConversions", []) if c["currency"] == quote_currency), None)
            if factors is None:
                raise ValidationError("Broker tidak mengirim faktor konversi yang diperlukan.")
        commission = s.get("commission", {})
        per_unit = (2 * float(commission["commission"]) / float(commission["unitsTraded"])) if commission else 0
        stamp = now_utc()
        return {"pair": pair, "source": f"OANDA-{self.environment}", "simulated": False,
                "as_of": iso(stamp), "frames": frames,
                "quote": {"bid": float(quote["bids"][0]["price"]), "ask": float(quote["asks"][0]["price"]),
                          "time": quote["time"], "tradeable": quote["tradeable"]},
                "instrument": {"pair": pair, "pip_size": 10 ** s["pipLocation"],
                    "tick_size": 10 ** (-s["displayPrecision"]),
                    "contract_size": number(contract_size, "contract_size", positive=True),
                    "units_step": 10 ** (-s["tradeUnitsPrecision"]), "min_units": float(s["minimumTradeSize"]),
                    "max_units": float(s["maximumOrderUnits"]), "margin_rate": float(s["marginRate"]),
                    "commission_per_unit_roundtrip": per_unit,
                    "min_commission_roundtrip": 2 * float(commission.get("minimumCommission", 0)),
                    "spec_source": "OANDA account instruments; lot convention supplied by user"},
                "account": {"currency": account["currency"], "equity": float(account["NAV"]),
                    "free_margin": float(account["marginAvailable"]),
                    "open_trade_count": int(account["openTradeCount"]),
                    "day_start_equity": number(day_start_equity, "day_start_equity", positive=True), "as_of": iso(account_stamp)},
                "conversion": {"account_currency": account["currency"], "quote_currency": quote_currency,
                    "loss_factor": float(factors["accountLoss"]), "gain_factor": float(factors["accountGain"]),
                    "position_factor": float(factors["positionValue"]), "time": pricing["time"]},
                "fundamentals": fundamentals}


def alpha_vantage_sentiment(currency: str, *, api_key=None, transport=request_json) -> dict:
    """Relevance-weighted FOREX ticker score, not the overall article score."""
    if currency not in ("EUR", "USD", "GBP", "JPY", "AUD"):
        raise ValidationError("Mata uang sentimen tidak didukung.")
    key = api_key or os.getenv("ALPHAVANTAGE_API_KEY")
    if not key:
        raise ValidationError("ALPHAVANTAGE_API_KEY diperlukan.")
    now = now_utc()
    query = urlencode({"function": "NEWS_SENTIMENT", "tickers": f"FOREX:{currency}",
                       "time_from": (now - timedelta(hours=24)).strftime("%Y%m%dT%H%M"),
                       "sort": "LATEST", "limit": 100, "apikey": key})
    data = transport("https://www.alphavantage.co/query?" + query)
    if "feed" not in data:
        raise ValidationError("Sentimen tidak tersedia; periksa kuota/entitlement Alpha Vantage.")
    numerator = denominator = 0.0
    count = 0
    sources = []
    for article in data["feed"]:
        try:
            published = datetime.strptime(article["time_published"], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
        except (ValueError, KeyError, TypeError):
            continue
        if not now - timedelta(hours=24) <= published <= now:
            continue
        for ticker in article.get("ticker_sentiment", []):
            if ticker["ticker"] not in (currency, f"FOREX:{currency}"):
                continue
            relevance = number(ticker["relevance_score"], "relevance", minimum=0)
            if relevance < 0.1:
                continue
            score = number(ticker["ticker_sentiment_score"], "ticker_sentiment_score")
            if not -1 <= score <= 1:
                raise ValidationError("Skor sentimen provider tidak valid.")
            numerator += score * relevance
            denominator += relevance
            count += 1
            sources.append({"title": article.get("title", ""), "url": article.get("url", ""),
                            "time_published": article.get("time_published", "")})
    return {"currency": currency, "score": numerator / denominator if denominator else 0,
            "sample_count": count, "as_of": iso(now), "source": "Alpha Vantage NEWS_SENTIMENT", "articles": sources}
