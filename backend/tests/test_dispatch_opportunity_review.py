import sys
from pathlib import Path
from unittest.mock import patch

import mongomock
from bson import ObjectId
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import services.dispatch_opportunity_service as service
import routes.dispatch_opportunities as routes


def test_approve_sets_charge_and_is_idempotent():
    db = mongomock.MongoClient().dispatch_review_test
    opportunity_id = ObjectId()
    reviewer_id = ObjectId()
    db.dispatch_opportunities.insert_one({
        "_id": opportunity_id,
        "opportunity_id": "DO-TEST-1",
        "status": "submitted",
        "customer_name": "Ada Mensah",
        "customer_phone": "0200000000",
        "pickup_location": "Accra",
        "destination": "Tema",
        "vehicle_type_needed": "Van",
        "preferred_pickup_date": "2026-08-28",
        "preferred_pickup_time": "09:00",
        "trip_purpose": "PASSENGER",
        "dispatch_classification": "COMMERCIAL",
        "proposed_charge": 100,
        "approved_charge": None,
        "submitted_by_driver_id": ObjectId(),
    })
    patches = [
        patch.object(service, "get_collection", side_effect=lambda name: db[name]),
        patch.object(service, "_batch_enrich_dispatch_opportunities", side_effect=lambda docs: docs),
        patch.object(service, "_validate_complete_opportunity"),
        patch.object(service, "resolve_action_notifications"),
        patch.object(service, "create_notification"),
    ]
    for item in patches:
        item.start()
    try:
        first = service.approve_dispatch_opportunity(
            str(opportunity_id), {"approved_charge": 125},
            current_user_id=str(reviewer_id), current_role="admin",
        )
        second = service.approve_dispatch_opportunity(
            str(opportunity_id), {"approved_charge": 999},
            current_user_id=str(reviewer_id), current_role="admin",
        )
    finally:
        for item in reversed(patches):
            item.stop()

    assert first["status"] == second["status"] == "approved"
    assert first["approved_charge"] == second["approved_charge"] == 125
    assert db.dispatch_opportunities.count_documents({"status": "approved"}) == 1


def test_approve_http_route_returns_success_and_is_retry_safe():
    db = mongomock.MongoClient().dispatch_review_route_test
    opportunity_id = ObjectId()
    reviewer_id = ObjectId()
    db.users.insert_one({"_id": reviewer_id, "status": "active", "role": "admin"})
    db.dispatch_opportunities.insert_one({
        "_id": opportunity_id, "opportunity_id": "DO-ROUTE-1", "status": "submitted",
        "customer_name": "Ada Mensah", "customer_phone": "0200000000",
        "pickup_location": "Accra", "destination": "Tema", "vehicle_type_needed": "Van",
        "preferred_pickup_date": "2026-08-28", "preferred_pickup_time": "09:00",
        "trip_purpose": "PASSENGER", "dispatch_classification": "COMMERCIAL",
        "proposed_charge": 100, "submitted_by_driver_id": ObjectId(),
    })
    app = Flask(__name__)
    app.config.update(TESTING=True, JWT_SECRET_KEY="test", MONGO_URI="mongodb://test")
    JWTManager(app)
    app.register_blueprint(routes.dispatch_opportunities_bp, url_prefix="/api/dispatch-opportunities")
    def json_safe(docs):
        result = []
        for doc in docs:
            item = dict(doc)
            for key, value in list(item.items()):
                if isinstance(value, ObjectId):
                    item[key] = str(value)
            result.append(item)
        return result

    patches = [
        patch.object(service, "get_collection", side_effect=lambda name: db[name]),
        patch.object(service, "_batch_enrich_dispatch_opportunities", side_effect=json_safe),
        patch.object(service, "_validate_complete_opportunity"),
        patch.object(service, "resolve_action_notifications"),
        patch.object(service, "create_notification"),
    ]
    # The decorator resolves account state through its own imported collection helper.
    patches.append(patch("utils.decorators.get_collection", side_effect=lambda name: db[name]))
    for item in patches:
        item.start()
    try:
        with app.test_request_context():
            token = create_access_token(identity=str(reviewer_id), additional_claims={"role": "admin"})
        client = app.test_client()
        first = client.patch(f"/api/dispatch-opportunities/{opportunity_id}/approve", json={"approved_charge": 125}, headers={"Authorization": f"Bearer {token}"})
        second = client.patch(f"/api/dispatch-opportunities/{opportunity_id}/approve", json={"approved_charge": 999}, headers={"Authorization": f"Bearer {token}"})
    finally:
        for item in reversed(patches):
            item.stop()
    assert first.status_code == second.status_code == 200
    assert first.get_json()["data"]["opportunity"]["status"] == "approved"
    assert db.dispatch_opportunities.find_one({"_id": opportunity_id})["approved_charge"] == 125
