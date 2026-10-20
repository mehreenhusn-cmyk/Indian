"""Demo with the bot's REAL strategy (ABCDStrategy) on synthetic candles - no
account/network needed.   Run from backend/:  python india_demo.py"""
from recovered_bot.strategy import ABCDStrategy
from recovered_bot.india_data import ReplayProvider, synthetic_candles
from recovered_bot.india_paper import IndiaPaperEngine
from recovered_bot.india_bridge import IndiaStrategyRunner

if __name__ == "__main__":
    data = {"NIFTY": synthetic_candles(24100, 15, seed=1),
            "BANKNIFTY": synthetic_candles(52300, 15, seed=2),
            "FINNIFTY": synthetic_candles(24500, 15, seed=3)}
    prov = ReplayProvider(data)
    eng = IndiaPaperEngine(prov, state_path="india_paper_state.json")
    runner = IndiaStrategyRunner(prov, eng, ABCDStrategy(lookback_len=200, ema_length=50))
    while prov.step():
        eng.on_tick()
        for u in data:
            runner.run(u)
    eng.close_all("END")
    print(eng.stats())
    for t in eng.closed[-5:]:
        print(t["underlying"], t["action"], t["contract"]["key"], t["reason"], t["pnl"])
