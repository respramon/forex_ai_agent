"""Validated boundary types. All candle timestamps denote CLOSE time, UTC."""

from __future__ import annotations

import math
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from typing import Any

PAIRS = ("EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "XAU/USD")
SECONDS = {"M5": 300, "M15": 900, "H1": 3600, "H4": 14400, "Daily": 86400}
CONTEXT = {"M5": ("M15", "H1"), "M15": ("H1", "H4"),
           "H1": ("H4", "Daily"), "H4": ("Daily",), "Daily": ("H4",)}


class ValidationError(ValueError):
    pass


def utc(value: str | datetime) -> datetime:
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValidationError("Timestamp harus ISO 8601 dengan zona waktu.") from exc
    if dt.tzinfo is None:
        raise ValidationError("Timestamp tanpa zona waktu ditolak.")
    return dt.astimezone(timezone.utc)


def iso(value: datetime) -> str:
    return utc(value).isoformat().replace("+00:00", "Z")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def number(value: Any, name: str, *, minimum: float | None = None,
           positive: bool = False) -> float:
    if isinstance(value, bool):
        raise ValidationError(f"{name} harus angka, bukan boolean.")
    try:
        n = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValidationError(f"{name} harus angka.") from exc
    if not math.isfinite(n) or (positive and n <= 0) or (minimum is not None and n < minimum):
        raise ValidationError(f"{name} berada di luar batas valid.")
    return n


def pair_name(value: str) -> str:
    value = str(value).upper().replace("_", "/")
    if value not in PAIRS:
        raise ValidationError(f"Pair harus salah satu: {', '.join(PAIRS)}")
    return value


@dataclass(frozen=True)
class Candle:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0

    @classmethod
    def parse(cls, raw: dict) -> "Candle":
        if raw.get("complete", True) is not True:
            raise ValidationError("Candle belum tutup tidak boleh dianalisis.")
        o, h, l, c = [number(raw[k], k, positive=True) for k in ("open", "high", "low", "close")]
        if l > min(o, c) or h < max(o, c) or h < l:
            raise ValidationError("OHLC tidak konsisten.")
        return cls(utc(raw["time"]), o, h, l, c, number(raw.get("volume", 0), "volume", minimum=0))


@dataclass(frozen=True)
class Instrument:
    pair: str
    pip_size: float
    tick_size: float
    contract_size: float
    units_step: float
    min_units: float
    max_units: float
    margin_rate: float
    commission_per_unit_roundtrip: float = 0
    min_commission_roundtrip: float = 0
    spec_source: str = "user-supplied"

    @classmethod
    def parse(cls, raw: dict) -> "Instrument":
        names = ("pip_size", "tick_size", "contract_size", "units_step", "min_units", "max_units", "margin_rate")
        values = {k: number(raw[k], k, positive=True) for k in names}
        if values["min_units"] > values["max_units"] or values["margin_rate"] > 1:
            raise ValidationError("Spesifikasi instrumen tidak konsisten.")
        for key in ("commission_per_unit_roundtrip", "min_commission_roundtrip"):
            values[key] = number(raw.get(key, 0), key, minimum=0)
        return cls(pair_name(raw["pair"]), **values, spec_source=str(raw.get("spec_source", "user-supplied")))


@dataclass(frozen=True)
class Account:
    equity: float
    free_margin: float
    day_start_equity: float
    currency: str
    as_of: datetime

    @classmethod
    def parse(cls, raw: dict) -> "Account":
        currency = str(raw["currency"]).upper()
        if len(currency) != 3 or not currency.isalpha():
            raise ValidationError("Mata uang akun harus kode tiga huruf.")
        return cls(number(raw["equity"], "equity", positive=True),
                   number(raw["free_margin"], "free_margin", minimum=0),
                   number(raw["day_start_equity"], "day_start_equity", positive=True),
                   currency, utc(raw["as_of"]))


@dataclass(frozen=True)
class RiskPolicy:
    risk_fraction: float = 0.01
    min_rr: float = 2.0
    atr_stop_multiplier: float = 1.5
    max_daily_loss_fraction: float = 0.03
    max_portfolio_risk_fraction: float = 0.04
    max_currency_risk_fraction: float = 0.03
    max_trades_per_day: int = 3
    max_consecutive_losses: int = 3
    cooldown_minutes: int = 60
    max_spread_atr_fraction: float = 0.15
    max_quote_age_seconds: int = 120
    calendar_max_age_minutes: int = 15
    news_before_minutes: int = 30
    news_after_minutes: int = 30
    slippage_atr_fraction: float = 0.05
    max_margin_fraction: float = 0.5
    min_confirmations: int = 4

    def __post_init__(self):
        for f in fields(self):
            n = number(getattr(self, f.name), f.name, positive=True)
            if f.type == "int" and n != int(n):
                raise ValidationError(f"{f.name} harus bilangan bulat.")
            object.__setattr__(self, f.name, int(n) if f.type == "int" else n)
        if not 0 < self.risk_fraction <= 0.02:
            raise ValidationError("Risiko per transaksi harus > 0 dan <= 2%.")
        if self.min_rr < 2 or not 3 <= self.min_confirmations <= 5:
            raise ValidationError("RR minimal 2 dan konfirmasi minimal 3–5.")
        if any(getattr(self, k) > 1 for k in ("max_daily_loss_fraction", "max_portfolio_risk_fraction",
                "max_currency_risk_fraction", "max_spread_atr_fraction", "max_margin_fraction", "slippage_atr_fraction")):
            raise ValidationError("Fraksi harus <= 1.")

    @classmethod
    def parse(cls, raw: dict | None = None) -> "RiskPolicy":
        raw = raw or {}
        unknown = set(raw) - {f.name for f in fields(cls)}
        if unknown:
            raise ValidationError(f"Konfigurasi tidak dikenal: {sorted(unknown)}")
        return cls(**raw)
