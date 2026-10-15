from dataclasses import asdict
import numpy as np
import pandas as pd
import pytest
from momentum import Spec, CATALOG, calculate, cross_transform, screen
from market_data import demo_prices
from service import evaluate
import storage

def exponential(daily=.001, count=1700):
    c=100*np.exp(np.arange(count)*daily)
    return pd.DataFrame({'Open':c,'High':c*1.01,'Low':c*.99,'Close':c,'Volume':100}, index=pd.bdate_range('2018-01-01',periods=count))

def test_known_returns_regression_and_skip():
    f=exponential()
    assert calculate(f,Spec(n=60))['value']==pytest.approx(np.expm1(.06))
    assert calculate(f,Spec(kind='log',n=60))['value']==pytest.approx(.06)
    assert calculate(f,Spec(kind='skip',n=252,skip=21))['value']==pytest.approx(np.expm1(.231))
    reg=calculate(f,Spec(kind='regression',n=60))
    assert reg['details']['Beta']==pytest.approx(.001)
    assert reg['details']['R²']==pytest.approx(1)
    assert reg['value']==pytest.approx(.001)

def test_multi_custom_periods_and_weights():
    result=calculate(exponential(count=45),Spec(kind='multi',horizons=[20,40],weights=[2.,-1.]))
    assert result['value']==pytest.approx(2*np.expm1(.02)-np.expm1(.04))
    assert result['details']['M_20']==pytest.approx(np.expm1(.02))
    assert result['details']['M_40']==pytest.approx(np.expm1(.04))

def test_relative_alignment():
    a=exponential(); b=exponential(.0005)
    assert calculate(a,Spec(kind='relative'),b)['value']==pytest.approx(np.expm1(.06)-np.expm1(.03))
    with pytest.raises(ValueError,match='日期|日期|不|불일치|부족'): calculate(a,Spec(kind='relative'),b.iloc[:-1])

def test_downside_uses_all_returns_and_zero_denominator():
    f=exponential(); f['Close']=np.resize([100.,110.,99.,108.9],len(f))
    s=Spec(kind='down',n=60); r=f.Close.pct_change().iloc[-60:]
    expected=(f.Close.iloc[-1]/f.Close.iloc[-61]-1)/np.sqrt(np.mean(np.minimum(r,0)**2))
    assert calculate(f,s)['value']==pytest.approx(expected)
    with pytest.raises(ValueError,match='분모'): calculate(exponential(),Spec(kind='down'))

@pytest.mark.parametrize('kind',list(CATALOG))
def test_every_formula_finite(kind):
    prices=demo_prices(); result=calculate(prices['QQQ'],Spec(kind=kind,n=120),prices['SPY'])
    assert np.isfinite(result['value'])

def test_rsi_adx_flat_and_monotonic():
    assert calculate(exponential(),Spec(kind='rsi',n=14))['value']==100
    assert calculate(exponential(0),Spec(kind='rsi',n=14))['value']==50
    assert calculate(exponential(),Spec(kind='adx',n=14))['value']==pytest.approx(100)
    assert calculate(exponential(),Spec(kind='mdd'))['value']==0

def rules():
    return [dict(id=x,op='>=',threshold=1,upper=2,top=3,ascending=False,rank_weight=1.) for x in ['f1','f2','f3']]

def test_user_intersection_example_and_independent_visibility():
    table=pd.DataFrame({'f1':[1,1,1,0,0],'f2':[0,1,1,1,0],'f3':[0,1,0,1,1]},index=list('ABCDE'))
    mask,ranks,steps=screen(table,rules(),True)
    assert table.index[mask].tolist()==['B']
    assert [x[2] for x in steps]==[3,2,1]
    independent,_,_=screen(table,rules(),False)
    assert table.index[independent['f1']].tolist()==list('ABC')
    assert table.index[independent['f2']].tolist()==list('BCD')
    assert table.index[independent['f3']].tolist()==list('BDE')
    assert ranks.loc['B','Overall Rank']==1

def test_ranking_direction_ties_and_missing():
    table=pd.DataFrame({'f1':[3.,2.,2.,np.nan]},index=list('ABCD'))
    rule=rules()[:1]; rule[0].update(op='Top N',top=2)
    mask,ranking,_=screen(table,rule,True)
    assert mask.tolist()==[True,True,True,False]
    assert ranking.loc['A','Composite Score']==100
    assert pd.isna(ranking.loc['D','Composite Score'])
    rule[0]['ascending']=True
    _,ranking,_=screen(table,rule,True)
    assert ranking.loc['B','Composite Score']>ranking.loc['A','Composite Score']

def test_cross_z_and_ties():
    result={t:dict(value=v,details={}) for t,v in zip('ABC',[.1,.2,.3])}
    cross_transform(result,'z')
    assert result['B']['value']==pytest.approx(0,abs=1e-14)
    assert result['C']['value']>1
    ties={t:dict(value=.1,details={}) for t in 'AB'}
    assert cross_transform(ties,'cross')['A']['value']==50
    with pytest.raises(ValueError): cross_transform({t:dict(value=.1,details={}) for t in 'AB'},'z')

def test_database_save_update_delete(tmp_path,monkeypatch):
    monkeypatch.setattr(storage,'ROOT',tmp_path)
    ident=storage.save('one',{'values':[1,2]})
    storage.save('two',{'values':[3]},ident)
    assert len(storage.list_records())==1
    assert storage.list_records()[0]['payload']['values']==[3]
    storage.delete(ident)
    assert storage.list_records()==[]

def test_service_individual_filter_groups():
    cards=[dict(id=str(i),name=f'rule{i}',spec=asdict(Spec(n=n)),rule={k:v for k,v in rules()[0].items() if k!='id'}) for i,n in enumerate([20,60,120])]
    for card in cards: card['rule']['threshold']=-1
    cfg=dict(cards=cards,demo=True,mode='필터',scope='전체',combine='개별 (각 결과 유지)',asof=pd.Timestamp('2026-09-30').date(),refresh=False,references='')
    result=evaluate(cfg)
    assert len(result['groups'])==3
    assert all(len(x)==8 for x in result['groups'].values())
