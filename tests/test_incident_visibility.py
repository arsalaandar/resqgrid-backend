import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.core.security import create_access_token
from app.models.incident import Incident
from app.models.user import User
from app.services.incident import purge_stale_drafts


def make_user(db_session, phone, role, **extra):
    user = User(
        phone=phone,
        role=role,
        is_active=True,
        is_verified=True,
        must_change_password=False,
        **extra,
    )
    db_session.add(user)
    db_session.flush()
    return user


def make_incident(db_session, reporter, status="REPORTED", **overrides):
    values = {
        "reporter_id": reporter.id,
        "description": "Flood water has entered the residential area.",
        "latitude": 34.0837,
        "longitude": 74.7973,
        "district": "Srinagar",
        "tehsil": "Srinagar North",
        "status": status,
        "departmental_details": {},
    }
    values.update(overrides)
    incident = Incident(**values)
    db_session.add(incident)
    db_session.flush()
    return incident


def headers(user):
    token = create_access_token(user.id, token_version=user.token_version)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def citizen(db_session):
    return make_user(db_session, "+919100000801", "CITIZEN")


@pytest.fixture
def official(db_session):
    return make_user(
        db_session,
        "+919100000802",
        "OFFICIAL",
        assigned_district="Srinagar",
        assigned_tehsil="Srinagar North",
    )


@pytest.fixture
def admin(db_session):
    return make_user(db_session, "+919100000803", "ADMIN")


# ---------------------------------------------------------------- visibility


@pytest.mark.asyncio
async def test_official_cannot_see_another_persons_draft(
    auth_client, db_session, citizen, official
):
    draft = make_incident(db_session, citizen, status="DRAFT")

    by_id = await auth_client.get(
        f"/api/v1/incidents/{draft.id}", headers=headers(official)
    )
    listing = await auth_client.get(
        "/api/v1/incidents/assigned", headers=headers(official)
    )

    assert by_id.status_code == 404
    assert draft.id not in {item["id"] for item in listing.json()}


@pytest.mark.asyncio
async def test_official_sees_reported_incident_in_jurisdiction(
    auth_client, db_session, citizen, official
):
    reported = make_incident(db_session, citizen, status="REPORTED")

    by_id = await auth_client.get(
        f"/api/v1/incidents/{reported.id}", headers=headers(official)
    )
    listing = await auth_client.get(
        "/api/v1/incidents/assigned", headers=headers(official)
    )

    assert by_id.status_code == 200
    assert reported.id in {item["id"] for item in listing.json()}


@pytest.mark.asyncio
async def test_official_still_sees_their_own_draft(
    auth_client, db_session, official
):
    own_draft = make_incident(db_session, official, status="DRAFT")

    by_id = await auth_client.get(
        f"/api/v1/incidents/{own_draft.id}", headers=headers(official)
    )
    listing = await auth_client.get(
        "/api/v1/incidents/assigned", headers=headers(official)
    )

    assert by_id.status_code == 200
    assert own_draft.id in {item["id"] for item in listing.json()}


@pytest.mark.asyncio
async def test_admin_can_still_see_drafts(
    auth_client, db_session, citizen, admin
):
    draft = make_incident(db_session, citizen, status="DRAFT")

    response = await auth_client.get(
        f"/api/v1/incidents/{draft.id}", headers=headers(admin)
    )

    assert response.status_code == 200


# ------------------------------------------------------------ admin filters


@pytest.mark.asyncio
async def test_admin_filters_and_paginates_real_data(
    auth_client, db_session, citizen, admin
):
    first = make_incident(db_session, citizen, status="DRAFT")
    second = make_incident(db_session, citizen, status="DRAFT")
    make_incident(db_session, citizen, status="REPORTED")
    make_incident(
        db_session,
        citizen,
        status="DRAFT",
        district="Baramulla",
        tehsil="Baramulla",
    )

    async def fetch(offset):
        response = await auth_client.get(
            "/api/v1/admin/incidents",
            headers=headers(admin),
            params={
                "district": "Srinagar",
                "status": "DRAFT",
                "limit": 1,
                "offset": offset,
            },
        )
        assert response.status_code == 200
        return response.json()

    page_one, page_two, page_three = await fetch(0), await fetch(1), await fetch(2)

    assert page_one["total"] == 2
    returned = [page_one["items"][0]["id"], page_two["items"][0]["id"]]
    assert sorted(returned) == sorted([first.id, second.id])
    assert page_three["items"] == []

    for page in (page_one, page_two):
        assert page["items"][0]["district"] == "Srinagar"
        assert page["items"][0]["status"] == "DRAFT"


@pytest.mark.asyncio
async def test_admin_filter_is_case_insensitive(
    auth_client, db_session, citizen, admin
):
    incident = make_incident(db_session, citizen)

    response = await auth_client.get(
        "/api/v1/admin/incidents",
        headers=headers(admin),
        params={"district": "sRiNaGaR"},
    )

    assert incident.id in {item["id"] for item in response.json()["items"]}


@pytest.mark.parametrize("field", ["district", "tehsil", "category"])
@pytest.mark.parametrize("wildcard", ["%", "_", "S%"])
@pytest.mark.asyncio
async def test_admin_filter_does_not_treat_wildcards_as_patterns(
    auth_client, db_session, citizen, admin, field, wildcard
):
    make_incident(db_session, citizen, incident_category="Flood")

    response = await auth_client.get(
        "/api/v1/admin/incidents",
        headers=headers(admin),
        params={field: wildcard},
    )

    assert response.status_code == 200
    assert response.json()["items"] == []


# ------------------------------------------------------- input validation


def payload(**overrides):
    body = {
        "incident_category": "Flood",
        "is_drill": False,
        "incident_datetime": datetime.now(UTC).isoformat(),
        "district": "Srinagar",
        "tehsil": "Srinagar North",
        "description": "Flood water has entered the residential area.",
        "latitude": 34.0837,
        "longitude": 74.7973,
        "damage_situation": "Moderate",
        "severity_level": "L1",
        "additional_remarks": "Immediate assessment required.",
        "departmental_details": {},
    }
    body.update(overrides)
    return body


async def post_incident(client, user, body=None, raw=None):
    if raw is not None:
        return await client.post(
            "/api/v1/incidents",
            headers={**headers(user), "Content-Type": "application/json"},
            content=raw,
        )
    return await client.post(
        "/api/v1/incidents", headers=headers(user), json=body
    )


@pytest.mark.asyncio
async def test_future_incident_time_is_rejected(auth_client, citizen):
    future = (datetime.now(UTC) + timedelta(hours=2)).isoformat()

    response = await post_incident(
        auth_client, citizen, payload(incident_datetime=future)
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_small_clock_skew_is_tolerated(auth_client, citizen):
    slightly_ahead = (datetime.now(UTC) + timedelta(minutes=2)).isoformat()

    response = await post_incident(
        auth_client, citizen, payload(incident_datetime=slightly_ahead)
    )

    assert response.status_code == 201


@pytest.mark.asyncio
async def test_past_incident_time_is_accepted(auth_client, citizen):
    earlier = (datetime.now(UTC) - timedelta(days=3)).isoformat()

    response = await post_incident(
        auth_client, citizen, payload(incident_datetime=earlier)
    )

    assert response.status_code == 201


@pytest.mark.asyncio
async def test_oversized_departmental_details_are_rejected(
    auth_client, citizen
):
    big = {"notes": "x" * 25_000}

    response = await post_incident(
        auth_client,
        citizen,
        payload(departmental_details={"evacuation": big}),
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_reasonable_departmental_details_are_accepted(
    auth_client, citizen
):
    response = await post_incident(
        auth_client,
        citizen,
        payload(departmental_details={"evacuation": {"people": 40}}),
    )

    assert response.status_code == 201


@pytest.mark.asyncio
async def test_nan_in_departmental_details_is_rejected_not_a_500(
    auth_client, citizen
):
    raw = json.dumps(payload(departmental_details={})).replace(
        '"departmental_details": {}',
        '"departmental_details": {"evacuation": {"x": NaN}}',
    )

    response = await post_incident(auth_client, citizen, raw=raw)

    assert response.status_code == 422


@pytest.mark.parametrize(
    "field",
    ["casualties", "people_missing", "houses_completely_damaged"],
)
@pytest.mark.asyncio
async def test_count_above_database_integer_range_is_rejected(
    auth_client, citizen, field
):
    response = await post_incident(
        auth_client, citizen, payload(**{field: 3_000_000_000})
    )

    # Without an upper bound this passed validation and failed at insert.
    assert response.status_code == 422


# -------------------------------------------------------------- stale drafts


def age(db_session, incident, days):
    db_session.execute(
        update(Incident)
        .where(Incident.id == incident.id)
        .values(created_at=datetime.now(UTC) - timedelta(days=days))
    )
    db_session.flush()
    db_session.expire_all()


def test_purge_deletes_only_old_drafts(db_session, citizen):
    old_draft = make_incident(db_session, citizen, status="DRAFT")
    fresh_draft = make_incident(db_session, citizen, status="DRAFT")
    old_reported = make_incident(db_session, citizen, status="REPORTED")
    age(db_session, old_draft, days=10)
    age(db_session, old_reported, days=10)

    # Capture ids first: the purge expires and deletes loaded instances.
    old_draft_id = old_draft.id
    fresh_draft_id = fresh_draft.id
    old_reported_id = old_reported.id

    deleted = purge_stale_drafts(db_session, older_than_days=7)

    remaining = set(
        db_session.scalars(
            select(Incident.id).where(
                Incident.id.in_(
                    [old_draft_id, fresh_draft_id, old_reported_id]
                )
            )
        )
    )

    assert deleted == 1
    assert remaining == {fresh_draft_id, old_reported_id}


def test_purge_rejects_nonsensical_window(db_session):
    with pytest.raises(ValueError):
        purge_stale_drafts(db_session, older_than_days=0)
