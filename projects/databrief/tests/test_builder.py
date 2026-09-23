import pytest
from app import builder,data
from test_data import RAW


def plan(**changes):
    return {'aggregate':'rows','metric':'','group':'','nulls':'exclude','order':'desc','filter':None,**changes}


def result(raw=RAW,**changes):
    parsed=data.parse(raw)
    proposal=builder.preview(parsed,plan(**changes))
    return data.query(parsed,proposal['sql'])['rows']


def test_metrics_and_explicit_null_policy():
    assert result()==[[3]]
    assert result(aggregate='count',metric='c2')==[[2]]
    assert result(aggregate='distinct',metric='c1')==[[2]]
    assert result(aggregate='avg',metric='c2')==[[2.5]]
    assert result(aggregate='avg',metric='c2',nulls='zero')==[[5/3]]
    assert result(aggregate='sum',metric='c3',group='c1')==[['搜索',30.0],['社交',30.0]]


def test_filters_and_empty_results():
    assert result(filter={'column':'c1','operator':'eq','value':'搜索'})==[[2]]
    assert result(filter={'column':'c2','operator':'ne','value':'2'})==[[1]]
    assert result(filter={'column':'c2','operator':'missing','value':''})==[[1]]
    assert result(filter={'column':'c3','operator':'gte','value':'20'})==[[1]]
    assert result(aggregate='sum',metric='c3',filter={'column':'c3','operator':'gte','value':'1000'})==[[None]]


def test_quote_is_data_not_sql_and_group_null_is_retained():
    raw="group,n\nO'Reilly,1\n,2\nother,3\n".encode()
    assert result(raw,filter={'column':'c1','operator':'eq','value':"O'Reilly"})==[[1]]
    assert result(raw,filter={'column':'c1','operator':'eq','value':"' OR 1=1 --"})==[[0]]
    assert result(raw,group='c1')==[[None,1],["O'Reilly",1],['other',1]]


@pytest.mark.parametrize('changes',[
    {'group':'c99'}, {'metric':'c1','aggregate':'avg'},
    {'metric':'c2','aggregate':'count','nulls':'zero'}, {'nulls':'zero'},
    {'filter':{'column':'c2','operator':'gte','value':'0 OR 1=1'}},
    {'filter':{'column':'c1','operator':'eq','value':' '}},
])
def test_incompatible_choices_rejected(changes):
    with pytest.raises(ValueError):builder.preview(data.parse(RAW),plan(**changes))
