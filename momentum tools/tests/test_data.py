from datetime import date
import pandas as pd
import market_data
from service import evaluate
from momentum import Spec
from dataclasses import asdict

def test_short_history_is_available_for_short_independent_formula(tmp_path,monkeypatch):
    monkeypatch.setattr(market_data,'CACHE',tmp_path)
    index=pd.bdate_range(end='2026-09-30',periods=35)
    f=pd.DataFrame({'Open':100.,'High':102.,'Low':99.,'Close':range(100,135),'Volume':100},index=index)
    multi=pd.concat({'IPO':f},axis=1)
    monkeypatch.setattr(market_data.yf,'download',lambda *a,**k:multi)
    prices,errors=market_data.load_prices(['IPO'],300,date(2026,9,30))
    assert 'IPO' in prices
    assert errors=={}

def test_demo_asof_has_no_future_prices():
    card=dict(id='one',name='one',ticker='SPY',spec=asdict(Spec(n=20)))
    cfg=dict(cards=[card],demo=True,mode='값 조회',references='',asof=date(2025,1,1),refresh=False)
    result=evaluate(cfg)
    assert result['date']=='2025-01-01'
