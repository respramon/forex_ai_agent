"""Read-only orchestration. A risk veto always wins over a technical candidate."""

from __future__ import annotations

import hashlib
import math
from datetime import timedelta
from . import fundamentals
from .indicators import analyze_frame
from .journal import Journal
from .models import (Account, Candle, CONTEXT, Instrument, RiskPolicy, SECONDS,
                     ValidationError, iso, now_utc, number, pair_name, utc)
from .risk import portfolio_gate, size_position
from .strategies import candidate


def empty_report(pair, timeframe, mode) -> dict:
    return {"pair": pair, "timeframe": timeframe, "mode": mode, "status": "NO_TRADE",
            "market_condition": "UNKNOWN", "trend": "UNKNOWN", "setup": "NONE",
            "entry_area": None, "stop_loss": None, "take_profit": None, "risk_reward": None,
            "reasons": [], "confidence": {"score": None, "label": "Belum dinilai",
                "meaning": "Skor kesesuaian aturan, bukan probabilitas menang."},
            "risks": ["Trading berleverage dapat merugi; stop loss tidak menjamin batas rugi saat gap."],
            "risk": None}


def _fresh(raw_time, now, max_seconds, name):
    stamp = utc(raw_time)
    if stamp > now or (now - stamp).total_seconds() > max_seconds:
        raise ValidationError(f"{name} kedaluwarsa atau berasal dari masa depan.")
    return stamp


def _frames(snapshot: dict, timeframe: str, now) -> dict:
    if timeframe not in SECONDS:
        raise ValidationError("Timeframe harus M5, M15, H1, H4, atau Daily.")
    parsed = {}
    for tf in (timeframe, *CONTEXT[timeframe]):
        raw = snapshot["frames"].get(tf)
        if not isinstance(raw, list) or not 250 <= len(raw) <= 5000:
            raise ValidationError(f"Timeframe {tf} memerlukan 250–5000 candle tutup.")
        candles = [Candle.parse(c) for c in raw]
        if any(b.time <= a.time for a, b in zip(candles, candles[1:])):
            raise ValidationError(f"Timestamp {tf} tidak urut atau duplikat.")
        _fresh(candles[-1].time, now, SECONDS[tf] * 1.25 + 60, f"Candle {tf}")
        # Recent discontinuities fail closed except the usual weekend closure.
        for a, b in zip(candles[-11:-1], candles[-10:]):
            gap = (b.time - a.time).total_seconds()
            weekend = a.time.weekday() in (4, 5) and b.time.weekday() in (6, 0) and gap <= 3 * 86400
            if gap > SECONDS[tf] * 1.5 and not weekend:
                raise ValidationError(f"Candle {tf} memiliki celah data terbaru yang tidak dapat dijelaskan.")
        parsed[tf] = candles
    return parsed


def _round_price(price, tick, upward):
    value = price / tick
    return round((math.ceil(value - 1e-10) if upward else math.floor(value + 1e-10)) * tick, 10)


class ForexAgent:
    def __init__(self, journal: Journal, policy: RiskPolicy | None = None):
        self.journal = journal
        self.policy = policy or RiskPolicy()

    def analyze(self, snapshot: dict, timeframe: str = "M15", mode: str = "analyst",
                proposed_trade: dict | None = None, *, clock=None) -> dict:
        """clock is for injected tests only; real callers use the wall clock."""
        report = empty_report(snapshot.get("pair", "UNKNOWN"), timeframe, mode)
        try:
            return self._analyze(snapshot, timeframe, mode, proposed_trade, clock, report)
        except (ValidationError, KeyError, TypeError, ValueError, IndexError, OverflowError) as exc:
            report["status"] = "NO_TRADE" if mode != "risk" else "REJECTED"
            report["reasons"].append(f"Input/data tidak valid: {exc}")
            self._clear_levels(report)
            return report

    @staticmethod
    def _clear_levels(report):
        for key in ("entry_area", "stop_loss", "take_profit", "risk_reward", "risk", "expires_at"):
            report[key] = None

    def _analyze(self, snapshot, timeframe, mode, proposed_trade, clock, report):
        if mode not in ("analyst", "signal", "risk"):
            raise ValidationError("Mode harus analyst/signal/risk; journal memakai perintah tersendiri.")
        pair = pair_name(snapshot["pair"])
        simulated = snapshot.get("simulated", False)
        if not isinstance(simulated, bool):
            raise ValidationError("simulated harus boolean.")
        now = utc(clock) if clock else utc(snapshot["as_of"]) if simulated else now_utc()
        _fresh(snapshot["as_of"], now, self.policy.max_quote_age_seconds, "Snapshot")
        report.update(pair=pair, as_of=iso(now), simulated=simulated, data_source=str(snapshot["source"]))
        if simulated:
            report["risks"].append("SIMULASI SINTETIS/HISTORIS — bukan harga atau sinyal pasar saat ini.")
        frames = _frames(snapshot, timeframe, now)
        technical = {tf: analyze_frame(c) for tf, c in frames.items()}
        frame = technical[timeframe]
        report.update(technical=technical, trend=frame["trend"],
                      market_condition="TRENDING" if frame["trend"] != "RANGE" else "RANGING")
        macro = fundamentals.evaluate(snapshot.get("fundamentals", {}), pair, now, self.policy)
        report["fundamentals"] = macro
        report["risks"].extend(macro["warnings"])
        report["reasons"].append(f"Trend {timeframe}: {frame['trend']}; struktur: {frame['structure']}.")
        report["reasons"].append("Konteks: " + ", ".join(f"{tf} {technical[tf]['trend']}" for tf in CONTEXT[timeframe]))
        if mode == "analyst":
            report["status"] = "ANALYSIS_ONLY"
            report["reasons"].extend(macro["blocks"])
            report["reasons"].append("Analyst Mode menyajikan observasi tanpa level transaksi.")
            return report
        policy = self.policy
        spec = Instrument.parse(snapshot["instrument"])
        if spec.pair != pair:
            raise ValidationError("Spesifikasi instrumen tidak cocok dengan pair.")
        account = Account.parse(snapshot["account"])
        _fresh(account.as_of, now, policy.max_quote_age_seconds, "Akun")
        conversion = snapshot["conversion"]
        _fresh(conversion["time"], now, policy.max_quote_age_seconds, "Konversi")
        if conversion["account_currency"] != account.currency:
            raise ValidationError("Mata uang konversi tidak cocok dengan akun.")
        if conversion.get("quote_currency") != pair.split("/")[1]:
            raise ValidationError("Mata uang quote konversi tidak cocok dengan instrumen.")
        for key in ("loss_factor", "gain_factor", "position_factor"):
            number(conversion[key], key, positive=True)
            if account.currency == conversion["quote_currency"] and abs(float(conversion[key]) - 1) > 1e-9:
                raise ValidationError("Konversi ke mata uang yang sama harus 1.")
        quote = snapshot["quote"]
        _fresh(quote["time"], now, policy.max_quote_age_seconds, "Quote")
        bid, ask = number(quote["bid"], "bid", positive=True), number(quote["ask"], "ask", positive=True)
        if ask < bid:
            raise ValidationError("Ask lebih rendah dari bid.")
        spread, volatility = ask - bid, frame["atr14"]
        report["spread"] = spread
        state = self.journal.state(now, policy, simulated)
        report["portfolio_state"] = state
        blocks = macro["blocks"] + portfolio_gate(account, state, policy, pair)
        open_count = number(snapshot["account"]["open_trade_count"], "open_trade_count", minimum=0)
        if int(open_count) != open_count or int(open_count) != state["open_positions"]:
            blocks.append("Jumlah transaksi terbuka akun berbeda dari jurnal; rekonsiliasi jurnal sebelum analisis risiko.")
        if now >= frames[timeframe][-1].time + timedelta(seconds=SECONDS[timeframe]):
            blocks.append("Candle pemicu sudah kedaluwarsa; tunggu snapshot dengan candle terbaru.")
        if quote.get("tradeable") is not True:
            blocks.append("Pasar/instrumen sedang tidak dapat diperdagangkan.")
        if volatility <= 0 or spread > volatility * policy.max_spread_atr_fraction:
            blocks.append("Spread terlalu lebar relatif terhadap ATR atau ATR tidak valid.")
        if volatility > frame["atr_reference"] * 2.5:
            blocks.append("Lonjakan volatilitas ekstrem; tunggu kondisi stabil.")
        if abs((bid + ask) / 2 - frame["close"]) > volatility * 0.5:
            blocks.append("Harga berjalan telah menjauh dari candle analisis; tunggu candle baru.")
        if blocks:
            report["reasons"].extend(blocks)
            report["status"] = "REJECTED" if mode == "risk" else "NO_TRADE"
            return report
        if mode == "risk":
            if proposed_trade is None:
                raise ValidationError("Risk Manager memerlukan proposed_trade.")
            side = proposed_trade["side"]
            entry, stop, target = [number(proposed_trade[k], k, positive=True) for k in ("entry", "stop", "target")]
            if abs(entry - (bid + ask) / 2) > volatility:
                raise ValidationError("Entry usulan lebih dari 1 ATR dari quote; refresh ketika mendekati entry.")
            setup, quality = "USER_PROPOSAL", None
            entry_area = [entry, entry]
            if abs(entry - stop) < volatility * policy.atr_stop_multiplier:
                raise ValidationError("Stop usulan terlalu sempit relatif terhadap ATR.")
        else:
            plan = candidate(frame, [technical[t] for t in CONTEXT[timeframe]], frames[timeframe], policy)
            report["checks"] = plan
            report["confidence"] = {"score": plan.get("quality_score", 0),
                                    "label": "Skor kesesuaian aturan",
                                    "meaning": "Bukan probabilitas menang; indikator dapat berkorelasi."}
            if not plan["side"]:
                report["reasons"].append(plan["reason"])
                return report
            side, setup, quality = plan["side"], plan["setup"], plan["quality_score"]
            report["reasons"].append(f"Konfirmasi {len(plan['confirmations'])}/5: " + ", ".join(plan["confirmations"]) +
                                     f"; RSI14 {frame['rsi14']:.1f}, MACD histogram {frame['macd_histogram']:.6g}.")
            score = macro["pair_sentiment"]
            if score is not None and (score < -0.4 if side == "BUY" else score > 0.4):
                report["reasons"].append("Sentimen pasangan berlawanan kuat dengan kandidat teknikal.")
                return report
            entry_area = [_round_price(frame["close"] - 0.1 * volatility, spec.tick_size, False),
                          _round_price(frame["close"] + 0.1 * volatility, spec.tick_size, True)]
            # Use the least favorable edge of the area for sizing and RR.
            entry = entry_area[1] if side == "BUY" else entry_area[0]
            recent = frames[timeframe][-5:]
            if side == "BUY":
                stop = min(entry - policy.atr_stop_multiplier * volatility, min(c.low for c in recent) - 0.2 * volatility)
            else:
                stop = max(entry + policy.atr_stop_multiplier * volatility, max(c.high for c in recent) + 0.2 * volatility)
            stop = _round_price(stop, spec.tick_size, side == "SELL")
            # Solve reward distance for net RR, including estimated variable costs.
            cost = (spread + volatility * policy.slippage_atr_fraction) * conversion["loss_factor"] + spec.commission_per_unit_roundtrip
            distance = (policy.min_rr * (abs(entry - stop) * conversion["loss_factor"] + cost) + cost) / conversion["gain_factor"]
            target = _round_price(entry + (distance if side == "BUY" else -distance), spec.tick_size, side == "BUY")
            obstacles = [level for observation in technical.values()
                         for level in observation["resistance" if side == "BUY" else "support"]]
            if any((entry < p <= target + 0.1 * volatility) if side == "BUY" else (target - 0.1 * volatility <= p < entry) for p in obstacles):
                report["reasons"].append("Support/resistance terkonfirmasi menghalangi target minimum 1:2.")
                return report
        risk = size_position(entry=entry, stop=stop, target=target, side=side, instrument=spec,
                             account=account, conversion=conversion, spread=spread,
                             slippage=volatility * policy.slippage_atr_fraction, policy=policy,
                             requested_units=proposed_trade.get("units") if mode == "risk" else None)
        reasons = risk["reasons"] + portfolio_gate(account, state, policy, pair, risk["estimated_loss"])
        if reasons:
            report["status"] = "REJECTED" if mode == "risk" else "NO_TRADE"
            report["reasons"].extend(reasons)
            if mode == "risk":
                report["risk_evaluation"] = risk
            return report
        report.update(status="APPROVED_RISK" if mode == "risk" else side, setup=setup,
                      entry_area=entry_area, stop_loss=stop, take_profit=target,
                      risk_reward=risk["net_rr"], risk=risk, side=side,
                      expires_at=iso(min(now + timedelta(seconds=SECONDS[timeframe]),
                                         frames[timeframe][-1].time + timedelta(seconds=SECONDS[timeframe]))))
        report["reasons"].append(f"{setup}: SL mengikuti ATR/struktur; RR bersih {risk['net_rr']:.2f}; sizing pada sisi area entry terburuk.")
        if mode == "risk":
            report["reasons"].append("APPROVED_RISK hanya kelayakan risiko; tidak mengonfirmasi strategi atau arah trading.")
            return report
        fingerprint = hashlib.sha256(f"{simulated}|{pair}|{timeframe}|{iso(frames[timeframe][-1].time)}|{side}".encode()).hexdigest()
        reason = self.journal.claim_signal(fingerprint, now, simulated, policy, report)
        if reason:
            report["status"] = "NO_TRADE"
            report["setup"] = "NONE"
            report.pop("side", None)
            report["reasons"].append(reason)
            self._clear_levels(report)
        else:
            report["signal_id"] = fingerprint
            report["risks"].append("Setup kedaluwarsa pada candle berikutnya; hitung ulang risiko sebelum entry manual.")
        return report


def format_report(report: dict) -> str:
    value = lambda x: "N/A" if x is None else x
    lines = [f"PAIR: {report['pair']}", f"TIMEFRAME: {report['timeframe']}",
             f"MARKET CONDITION: {report['market_condition']}", f"TREND: {report['trend']}",
             f"SETUP: {report['setup']} | {report['status']}", f"ENTRY AREA: {value(report['entry_area'])}",
             f"STOP LOSS: {value(report['stop_loss'])}", f"TAKE PROFIT: {value(report['take_profit'])}",
             f"RISK/REWARD: {'1:' + format(report['risk_reward'], '.2f') if report['risk_reward'] is not None else 'N/A'}",
             "ALASAN ANALISIS: " + " | ".join(report["reasons"]),
             f"TINGKAT KEPERCAYAAN: {value(report['confidence']['score'])} — {report['confidence']['meaning']}",
             "RISIKO YANG PERLU DIPERHATIKAN: " + " | ".join(report["risks"])]
    if report.get("risk"):
        r = report["risk"]
        lines.append(f"LOT SIZE: {r['lots']:.6f} ({r['units']:g} units); estimasi rugi {r['estimated_loss']:.2f} {r['account_currency']}")
    lines.append(f"DATA: {report.get('data_source', 'unknown')} | {report.get('as_of', 'N/A')}")
    return "\n".join(lines)
