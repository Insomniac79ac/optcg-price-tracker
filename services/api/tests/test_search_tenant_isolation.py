"""Real HTTP auth + two synthetic tenants; never connects to deployed data."""
from datetime import date, datetime, timezone
import inspect

import pytest
from sqlalchemy import event, select

from app.models import (
    Card, CollectionItem, CollectorActivityEvent, CollectorNote, GradingSubmission,
    MarketIntelligenceReport, MarketSignalEvent, SavedView, SearchHistory, User, WishlistItem,
)
from app.services.cache import reset_state_for_tests, set_cache
from app.services.opportunity_scoring import get_personal_opportunities
from app.services.search import get_suggestions, record_search_history, search
from app.services.saved_views import list_saved_views
from app.settings import settings
from tests._auth_helpers import make_bearer_token

PRIVATE = ['collection', 'wishlist', 'grading', 'notes', 'activity', 'signals', 'opportunities']


@pytest.fixture
def tenants(db_session):
    actors = {}
    for i, label in enumerate(['A', 'B'], 1):
        user = User(google_sub=f'tenant-{label}', email=f'{label}@example.invalid')
        db_session.add(user); db_session.flush()
        marker = f'TENANT_{label}_ONLY'
        card = Card(card_code=f'OP99-00{i}', name_en=f'Public card {label}', set_code='OP99', rarity='R', language='en')
        db_session.add(card); db_session.flush()
        item = CollectionItem(user_id=user.id, card_id=card.id, quantity=i+2, notes=marker)
        db_session.add(item); db_session.flush()
        now = datetime.now(timezone.utc)
        rows = {
            'collection': item,
            'wishlist': WishlistItem(user_id=user.id, card_id=card.id, priority='grail', notes=marker),
            'grading': GradingSubmission(collection_item_id=item.id, grading_company='PSA', submission_name=marker),
            'notes': CollectorNote(collection_item_id=item.id, card_id=card.id, title=marker, body=marker, note_type='general'),
            'activity': CollectorActivityEvent(collection_item_id=item.id, card_id=card.id, title=marker, message=marker, event_type='collection_item_added', event_source='collection'),
            'signals': MarketSignalEvent(collection_item_id=item.id, card_id=card.id, dedupe_key=marker, signal_type='price_up_7d', suggested_action='monitor_momentum', status='open', message=marker, first_seen_at=now, last_seen_at=now),
        }
        db_session.add_all(rows.values()); db_session.flush()
        ids = {kind: row.id for kind, row in rows.items()}; ids['opportunities'] = ids['signals']
        actors[label] = dict(user_id=user.id, card_id=card.id, code=card.card_code, marker=marker, ids=ids,
            headers={'Authorization': 'Bearer '+make_bearer_token(google_sub=user.google_sub, email=user.email)})
        db_session.add(SearchHistory(user_id=user.id, query=f'HISTORY_{label}_ONLY', result_count=0))
    db_session.add_all([
        SearchHistory(query='LEGACY_HISTORY', result_count=9),
        SavedView(name='LEGACY_VIEW', route_path='/collection', view_type='table'),
        CollectorNote(title='LEGACY_NOTE', body='TENANT_LEGACY', note_type='general'),
        CollectorActivityEvent(title='TENANT_LEGACY_ACTIVITY',event_type='collection_item_added',event_source='collection'),
        MarketSignalEvent(dedupe_key='legacy-signal',signal_type='price_up_7d',status='open',message='TENANT_LEGACY_SIGNAL',first_seen_at=datetime.now(timezone.utc),last_seen_at=datetime.now(timezone.utc)),
        MarketIntelligenceReport(report_date=date(2026, 1, 1), report_payload_json={'private': 'TENANT_REPORT'}),
    ])
    db_session.commit()
    return actors


@pytest.mark.parametrize('actor,other', [('A','B'), ('B','A')])
@pytest.mark.parametrize('provider', PRIVATE)
def test_private_rows_counts_metadata_and_pagination(client, tenants, actor, other, provider):
    own, foreign = tenants[actor], tenants[other]
    def run(q, offset=0):
        r = client.get('/search', params={'q':q, 'types':provider, 'limit':1, 'offset':offset, 'user_id':foreign['user_id']}, headers=own['headers'])
        assert r.status_code == 200
        return r.json()
    absent = run(foreign['marker'])
    assert absent['results'] == []
    assert absent['summary']['total_results'] == absent['summary']['by_type'][provider] == absent['pagination']['total'] == 0
    broad = run('TENANT_')
    assert [r['id'] for r in broad['results']] == [own['ids'][provider]]
    assert broad['summary']['total_results'] == broad['summary']['by_type'][provider] == broad['pagination']['total'] == 1
    assert broad['results'][0]['matched_fields']
    assert run('TENANT_', 1)['results'] == []
    exact = run(own['marker'])
    assert exact['results'] == broad['results']


@pytest.mark.parametrize('actor,other', [('A','B'), ('B','A')])
def test_all_provider_summary_and_reports_fail_closed(client, tenants, actor, other):
    d = client.get('/search', params={'q':'TENANT_'}, headers=tenants[actor]['headers']).json()
    assert d['summary']['total_results'] == len(PRIVATE)
    assert d['summary']['by_type']['reports'] == 0
    assert {r['type']:r['id'] for r in d['results']} == tenants[actor]['ids']
    assert client.get('/search', params={'q':'TENANT_REPORT', 'types':'reports'}, headers=tenants[actor]['headers']).json()['results'] == []


@pytest.mark.parametrize('actor,other', [('A','B'), ('B','A')])
def test_public_card_identity_with_personal_quantities_and_ranking(client, db_session, tenants, actor, other):
    own, foreign = tenants[actor], tenants[other]
    d = client.get('/search', params={'q':'Public card','types':'cards'}, headers=own['headers']).json()
    by_id = {r['id']: r for r in d['results']}
    assert by_id[foreign['card_id']]['metadata']['owned_quantity'] == 0
    assert by_id[own['card_id']]['metadata']['owned_quantity'] in (3,4)
    assert by_id[own['card_id']]['score'] == by_id[foreign['card_id']]['score'] + 5
    assert d['results'][0]['id'] == own['card_id']
    # Even when both own the same public card, quantities cannot be combined.
    db_session.add(CollectionItem(user_id=foreign['user_id'], card_id=own['card_id'], quantity=90));db_session.commit()
    after = client.get('/search', params={'q':'Public card','types':'cards'}, headers=own['headers']).json()
    assert after == d


@pytest.mark.parametrize('actor,other', [('A','B'), ('B','A')])
def test_personal_opportunity_inputs_and_score(client, db_session, tenants, actor, other):
    own, foreign = tenants[actor], tenants[other]
    db_session.get(WishlistItem, own['ids']['wishlist']).priority = 'low'
    db_session.commit()
    before = get_personal_opportunities(db_session, user_id=own['user_id']).model_dump()
    assert [o['event_id'] for o in before['opportunities']] == [own['ids']['signals']]
    # Other-account same-card inputs must not alter any score or enrichment.
    db_session.add_all([CollectionItem(user_id=foreign['user_id'], card_id=own['card_id'], quantity=100),
        WishlistItem(user_id=foreign['user_id'], card_id=own['card_id'], priority='grail', status='target_hit', target_buy_price_jpy=999)])
    db_session.commit()
    assert get_personal_opportunities(db_session, user_id=own['user_id']).model_dump() == before


@pytest.mark.parametrize('actor,other', [('A','B'), ('B','A')])
def test_suggestions_history_and_identity(client, db_session, tenants, actor, other):
    own, foreign = tenants[actor], tenants[other]
    d = client.get('/search/suggestions', params={'limit':50}, headers=own['headers']).json()
    labels = [s['label'] for s in d['suggestions']]
    assert f'HISTORY_{actor}_ONLY' in labels
    assert f'HISTORY_{other}_ONLY' not in labels
    assert 'LEGACY_HISTORY' not in labels and 'LEGACY_NOTE' not in labels
    assert any(s['type']=='note' and s['label']==own['marker'] for s in d['suggestions'])
    assert all(foreign['marker'] not in s['label'] and foreign['code'] not in s['label'] for s in d['suggestions'])
    for q in [foreign['marker'], f'HISTORY_{other}_ONLY', foreign['code']]:
        assert client.get('/search/suggestions', params={'q':q,'limit':50}, headers=own['headers']).json()['suggestions'] == []
    client.get('/search', params={'q':f'NEW_HISTORY_{actor}'}, headers=own['headers'])
    row = db_session.scalar(select(SearchHistory).where(SearchHistory.query==f'NEW_HISTORY_{actor}'))
    assert row.user_id == own['user_id']


def test_suggestion_cache_separates_accounts_and_ignores_legacy(client, monkeypatch, tenants):
    monkeypatch.setattr(settings,'CACHE_ENABLED',True);monkeypatch.setattr(settings,'CACHE_BACKEND','memory')
    reset_state_for_tests()
    try:
        set_cache('search_suggestions:None:50', {'suggestions':[{'label':'LEGACY_CACHE','url':'/search','type':'recent_search'}]},60)
        a = client.get('/search/suggestions',params={'limit':50},headers=tenants['A']['headers'])
        b = client.get('/search/suggestions',params={'limit':50},headers=tenants['B']['headers'])
        again = client.get('/search/suggestions',params={'limit':50},headers=tenants['A']['headers'])
        assert [r.headers['x-cache'] for r in [a,b,again]] == ['MISS','MISS','HIT']
        assert a.json() == again.json() and a.json() != b.json()
        assert 'LEGACY_CACHE' not in a.text+b.text
        assert tenants['B']['marker'] not in a.text and tenants['A']['marker'] not in b.text
    finally:
        reset_state_for_tests()


@pytest.mark.parametrize('actor,other', [('A','B'), ('B','A')])
def test_saved_views_all_operations_are_personal(client, db_session, tenants, actor, other):
    own, foreign = tenants[actor], tenants[other]
    views = {}
    for label, user in [(actor,own),(other,foreign)]:
        r=client.post('/saved-views',json={'name':'Same personal name','route_path':'/collection','view_type':'table','is_default':True,'user_id':foreign['user_id']},headers=user['headers'])
        assert r.status_code==201,r.text
        views[label]=r.json()['id']
        assert db_session.get(SavedView,views[label]).user_id==user['user_id']
    foreign_id=views[other]
    d=client.get('/saved-views',headers=own['headers']).json()
    assert [v['id'] for v in d['items']]==[views[actor]] and d['pagination']['total']==1
    for method,path,body in [('get','',None),('patch','',{'name':'changed'}),('delete','',None),('post','/use',None),('post','/set-default',None)]:
        r=client.request(method,f'/saved-views/{foreign_id}{path}',json=body,headers=own['headers'])
        missing=client.request(method,f'/saved-views/999999{path}',json=body,headers=own['headers'])
        assert r.status_code==missing.status_code==404
        assert r.json()['detail'].replace(str(foreign_id),'ID')==missing.json()['detail'].replace('999999','ID')
    client.post('/saved-views/clear-default',json={'route_path':'/collection','view_type':'table'},headers=own['headers'])
    db_session.expire_all();assert db_session.get(SavedView,foreign_id).is_default
    assert client.patch(f'/saved-views/{views[actor]}',json={'name':'Own renamed','user_id':foreign['user_id']},headers=own['headers']).status_code==200
    db_session.expire_all(); assert db_session.get(SavedView, views[actor]).user_id == own['user_id']
    assert client.post(f'/saved-views/{views[actor]}/use',headers=own['headers']).status_code==200
    assert client.post(f'/saved-views/{views[actor]}/set-default',headers=own['headers']).status_code==200
    assert client.delete(f'/saved-views/{views[actor]}',headers=own['headers']).status_code==204
    assert client.get('/saved-views',headers=own['headers']).json()['pagination']['total']==0
    legacy=db_session.scalar(select(SavedView).where(SavedView.user_id.is_(None)))
    assert legacy is not None
    assert client.get(f'/saved-views/{legacy.id}',headers=own['headers']).status_code==404


def test_ownerless_conflicting_and_indirect_parents(client, db_session, tenants):
    a,b=tenants['A'],tenants['B']
    rows=[]
    for model,extra in [(CollectorNote,dict(body='PARENT_MARKER',note_type='general')),
                        (CollectorActivityEvent,dict(message='PARENT_MARKER',event_type='collection_item_added',event_source='collection'))]:
        for links in [dict(wishlist_item_id=a['ids']['wishlist']),dict(grading_submission_id=a['ids']['grading']),dict(market_signal_event_id=a['ids']['signals'])]:
            rows.append(model(title='PARENT_MARKER',**links,**extra))
        rows.append(model(title='PARENT_CONFLICT',collection_item_id=a['ids']['collection'],wishlist_item_id=b['ids']['wishlist'],**extra))
        rows.append(model(title='PARENT_OWNERLESS',card_id=a['card_id'],**extra))
    db_session.add_all(rows);db_session.commit()
    for kind in ['notes','activity']:
        for who,expected in [('A',3),('B',0)]:
            d=client.get('/search',params={'q':'PARENT_','types':kind},headers=tenants[who]['headers']).json()
            assert d['summary']['total_results']==expected
            assert all(r['title']=='PARENT_MARKER' for r in d['results'])


def test_generated_sql_contains_owner_restrictions(client, db_session, tenants):
    queries=[]
    def capture(conn,cursor,statement,parameters,context,executemany):queries.append(statement)
    engine=db_session.get_bind();event.listen(engine,'before_cursor_execute',capture)
    try:
        for provider,table in [('collection','collection_items'),('wishlist','wishlist_items'),('grading','grading_submissions'),('notes','collector_notes'),('activity','collector_activity_events'),('signals','market_signal_events')]:
            queries.clear()
            client.get('/search',params={'q':'TENANT_','types':provider},headers=tenants['A']['headers'])
            selected=[q for q in queries if 'FROM '+table in q and q.startswith('SELECT')]
            assert selected
            assert all('WHERE' in q and 'user_id =' in q.split('WHERE',1)[1] for q in selected)
    finally:
        event.remove(engine,'before_cursor_execute',capture)


@pytest.mark.parametrize('func',[search,get_suggestions,record_search_history,get_personal_opportunities,list_saved_views])
def test_private_entry_points_require_identity(func):
    parameter=inspect.signature(func).parameters['user_id']
    assert parameter.default is inspect.Parameter.empty
    assert parameter.kind==inspect.Parameter.KEYWORD_ONLY


@pytest.mark.parametrize('bad',[None,0,-1,True])
def test_invalid_service_identity_fails_closed(db_session,bad):
    with pytest.raises(ValueError):search(db_session,'anything',user_id=bad)
    with pytest.raises(ValueError):get_suggestions(db_session,None,10,user_id=bad)
    with pytest.raises(ValueError):list_saved_views(db_session,user_id=bad)


def test_own_query_echo_is_not_other_users_history(client, db_session, tenants):
    a,b=tenants['A'],tenants['B']
    response=client.get('/search',params={'q':b['marker'],'types':'notes'},headers=a['headers'])
    assert response.json()['results']==[]
    rows=db_session.scalars(select(SearchHistory).where(SearchHistory.query==b['marker'])).all()
    assert [row.user_id for row in rows]==[a['user_id']]
    suggestions=client.get('/search/suggestions',params={'q':b['marker']},headers=a['headers']).json()['suggestions']
    assert suggestions and all(s['type']=='recent_search' for s in suggestions)
    # A sees the text A entered, never B's note or independently stored history.
    assert client.get('/search/suggestions',params={'q':'HISTORY_B_ONLY'},headers=a['headers']).json()['suggestions']==[]
