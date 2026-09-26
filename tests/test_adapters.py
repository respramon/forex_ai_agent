from copy import deepcopy
from datetime import timedelta
import unittest
from urllib.parse import urlsplit
from forex_agent.demo import make_snapshot
from forex_agent.llm import explain
from forex_agent.models import ValidationError, iso, now_utc, utc
from forex_agent.providers import OandaProvider, alpha_vantage_sentiment


class AdapterTests(unittest.TestCase):
    def test_oanda_read_only_mapping_uses_closed_candles_and_broker_spec(self):
        calls = []
        stamp = "2026-01-15T12:00:00Z"
        def transport(url, **kwargs):
            calls.append((url, kwargs))
            path = urlsplit(url).path
            if path.endswith("/instruments"):
                return {"instruments": [{"name": "USD_JPY", "pipLocation": -2, "displayPrecision": 3,
                    "tradeUnitsPrecision": 0, "minimumTradeSize": "1", "maximumOrderUnits": "1000000",
                    "marginRate": ".04"}]}
            if path.endswith("/summary"):
                return {"lastTransactionID": "10", "account": {"currency": "USD", "NAV": "10000", "marginAvailable": "9000", "openTradeCount": 0}}
            if path.endswith("/openTrades"):
                return {"lastTransactionID": "10", "trades": []}
            if path.endswith("/candles"):
                return {"candles": [{"time": stamp, "complete": complete, "mid": {"o": "150", "h": "151", "l": "149", "c": "150"}, "volume": 100}
                                    for complete in (True, False)]}
            if path.endswith("/pricing"):
                return {"time": stamp, "prices": [{"instrument": "USD_JPY", "time": stamp, "tradeable": True,
                    "bids": [{"price": "150"}], "asks": [{"price": "150.02"}]}],
                    "homeConversions": [{"currency": "JPY", "accountLoss": ".0067", "accountGain": ".0066", "positionValue": ".00665"}]}
            raise AssertionError(path)
        out = OandaProvider(token="fake", account_id="test-account", transport=transport).snapshot(
            "USD/JPY", contract_size=100000, day_start_equity=10000, fundamentals={"status": "unknown"})
        self.assertEqual(len(out["frames"]["M5"]), 1)
        self.assertEqual(out["frames"]["M5"][0]["time"], "2026-01-15T12:05:00Z")
        self.assertEqual(out["instrument"]["pip_size"], .01)
        self.assertEqual(out["conversion"]["loss_factor"], .0067)
        self.assertNotEqual(out["conversion"]["loss_factor"], out["conversion"]["gain_factor"])
        self.assertEqual(out["broker_open_trades"], [])
        self.assertTrue(all("payload" not in kwargs for _, kwargs in calls))
        self.assertTrue(all("fxpractice" in url for url, _ in calls))

    def test_oanda_snapshot_rejects_inconsistent_account_versions(self):
        def transport(url, **kwargs):
            path = urlsplit(url).path
            if path.endswith("/instruments"):
                return {"instruments": [{"name": "EUR_USD"}]}
            if path.endswith("/summary"):
                return {"lastTransactionID": "10", "account": {"openTradeCount": 0}}
            if path.endswith("/openTrades"):
                return {"lastTransactionID": "11", "trades": []}
            raise AssertionError(path)
        with self.assertRaisesRegex(ValidationError, "berubah"):
            OandaProvider(token="fake", account_id="test-account", transport=transport).snapshot(
                "EUR/USD", contract_size=100000, day_start_equity=10000, fundamentals={})

    def test_oanda_maps_each_open_ticket_and_its_attached_levels(self):
        stamp = "2026-01-15T12:00:00Z"
        def transport(url, **kwargs):
            path = urlsplit(url).path
            if path.endswith("/instruments"):
                return {"instruments": [{"name": "EUR_USD", "pipLocation": -4,
                    "displayPrecision": 5, "tradeUnitsPrecision": 0, "minimumTradeSize": "1",
                    "maximumOrderUnits": "1000000", "marginRate": ".04"}]}
            if path.endswith("/summary"):
                return {"lastTransactionID": "12", "account": {"currency": "USD", "NAV": "10000",
                    "marginAvailable": "9000", "openTradeCount": 1}}
            if path.endswith("/openTrades"):
                return {"lastTransactionID": "12", "trades": [{"id": "7", "state": "OPEN",
                    "instrument": "EUR_USD", "currentUnits": "10000", "price": "1.1",
                    "stopLossOrder": {"price": "1.09"},
                    "takeProfitOrder": {"price": "1.12"}}]}
            if path.endswith("/candles"):
                return {"candles": [{"time": stamp, "complete": True,
                    "mid": {"o": "1.1", "h": "1.11", "l": "1.09", "c": "1.1"}, "volume": 100}]}
            if path.endswith("/pricing"):
                return {"time": stamp, "prices": [{"instrument": "EUR_USD", "time": stamp,
                    "tradeable": True, "bids": [{"price": "1.1"}], "asks": [{"price": "1.10002"}]}],
                    "homeConversions": []}
            raise AssertionError(path)
        out = OandaProvider(token="fake", account_id="test-account", transport=transport).snapshot(
            "EUR/USD", contract_size=100000, day_start_equity=10000, fundamentals={})
        self.assertEqual(out["broker_open_trades"], [{"id": "7", "pair": "EUR/USD",
            "side": "BUY", "units": 10000, "entry": 1.1, "stop": 1.09,
            "target": 1.12, "loss_factor": 1}])

    def test_sentiment_filters_stale_articles_and_uses_currency_score(self):
        stamp = now_utc() - timedelta(minutes=1)
        def article(time, score):
            return {"time_published": time.strftime("%Y%m%dT%H%M%S"), "overall_sentiment_score": -.9,
                    "ticker_sentiment": [{"ticker": "USD", "relevance_score": .8, "ticker_sentiment_score": score}]}
        result = alpha_vantage_sentiment("USD", api_key="fake", transport=lambda *a, **k:
            {"feed": [article(stamp, .5), article(stamp - timedelta(days=2), -1)]})
        self.assertEqual(result["sample_count"], 1)
        self.assertEqual(result["score"], .5)

    def test_llm_output_does_not_mutate_or_receive_account(self):
        report = {"pair": "EUR/USD", "status": "NO_TRADE", "reasons": ["calendar unknown"],
                  "account": {"equity": 123456789}, "risk": {"units": 999999}, "stop_loss": None}
        original = deepcopy(report)
        calls = []
        def transport(url, **kwargs):
            calls.append(kwargs["payload"])
            return {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": "NO_TRADE tetap berlaku."}]}]}
        self.assertIn("NO_TRADE", explain(report, api_key="fake", model="test-model", transport=transport))
        self.assertEqual(report, original)
        self.assertNotIn("123456789", calls[0]["input"])
        self.assertNotIn("999999", calls[0]["input"])
        self.assertFalse(calls[0]["store"])

    def test_llm_failure_is_explicit(self):
        with self.assertRaises(ValidationError):
            explain({}, api_key="fake", model="test-model", transport=lambda *a, **k: {"status": "incomplete"})


if __name__ == "__main__":
    unittest.main()
