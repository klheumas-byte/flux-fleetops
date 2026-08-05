from unittest.mock import patch
import sys
from pathlib import Path
import mongomock
import pytest
from bson import ObjectId

BACKEND_DIR=Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:sys.path.insert(0,str(BACKEND_DIR))
import services.auth_service as auth
import services.branch_access_service as access
import services.branch_operations_service as branch_ops
import services.driver_scope_service as driver_scope
from utils.api_error import ApiError

@pytest.fixture
def domain():
    db=mongomock.MongoClient().flux_branch_ops; a,b=ObjectId(),ObjectId(); manager,other=ObjectId(),ObjectId()
    db.branches.insert_many([{"_id":a,"name":"Accra","status":"active"},{"_id":b,"name":"Kumasi","status":"active"}])
    db.users.insert_many([
        {"_id":manager,"full_name":"Accra Manager","role":"branch_manager","role_ids":["branch_manager"],"primary_branch_id":a,"allowed_branch_ids":[],"status":"active"},
        {"_id":other,"full_name":"Kumasi Manager","role":"branch_manager","role_ids":["branch_manager"],"primary_branch_id":b,"allowed_branch_ids":[],"status":"active"},
        {"_id":ObjectId(),"full_name":"Accra Agent","role":"field_agent","role_ids":["field_agent"],"primary_branch_id":a,"status":"active"},
        {"_id":ObjectId(),"full_name":"Kumasi Agent","role":"field_agent","role_ids":["field_agent"],"primary_branch_id":b,"status":"active"},
    ])
    patches=[patch.object(branch_ops,"get_collection",side_effect=lambda name:db[name]),patch.object(access,"get_collection",side_effect=lambda name:db[name]),patch.object(auth,"get_collection",side_effect=lambda name:db[name]),patch.object(driver_scope,"get_collection",side_effect=lambda name:db[name])]
    for item in patches:item.start()
    yield db,a,b,manager,other
    for item in reversed(patches):item.stop()

def test_manager_sees_only_branch_team_and_cross_branch_edit_is_forbidden(domain):
    db,a,b,manager,_=domain; result=branch_ops.list_branch_team(str(manager))
    assert [row["full_name"] for row in result["field_agents"]]==["Accra Agent"]
    other=db.users.find_one({"full_name":"Kumasi Agent"})
    with pytest.raises(ApiError) as denied:branch_ops.update_field_agent(str(manager),str(other["_id"]),{"full_name":"No"})
    assert denied.value.status_code==403

def test_manager_created_agent_is_forced_to_primary_branch_and_role(domain):
    db,a,b,manager,_=domain
    created=branch_ops.create_field_agent(str(manager),{"full_name":"New Agent","username":"new.agent","phone":"+233200000111","password":"secret12","role":"admin","primary_branch_id":str(b)})
    row=db.users.find_one({"_id":ObjectId(created["id"])})
    assert row["role"]=="field_agent" and row["role_ids"]==["field_agent"]
    assert row["primary_branch_id"]==a and row["created_by"]==manager

def test_driver_request_uses_existing_pending_approval_flow(domain):
    db,a,_,manager,_=domain
    created=branch_ops.create_driver_request(str(manager),{"full_name":"Requested Driver","username":"requested.driver","phone":"+233200000112","password":"secret12","notes":"Coverage","driver_profile":{"license_number":"DV-22"}})
    row=db.users.find_one({"_id":ObjectId(created["id"])})
    assert row["status"]=="inactive" and row["driver_profile"]["approval_status"]=="pending"
    assert row["driver_request_status"]=="PENDING_APPROVAL" and row["home_branch_id"]==a

def test_dashboard_counts_only_manager_branch(domain):
    db,a,b,manager,_=domain; today=branch_ops.date.today().isoformat(); oa=ObjectId()
    db.delivery_orders.insert_many([{"_id":oa,"branch_id":a,"customer_name":"A Customer","status":"CERTIFIED"},{"_id":ObjectId(),"branch_id":b,"customer_name":"B Customer","status":"CERTIFIED"}])
    db.delivery_batches.insert_many([{"_id":ObjectId(),"branch_id":a,"delivery_date":today,"status":"IN_PROGRESS","delivery_order_ids":[oa]},{"_id":ObjectId(),"branch_id":b,"delivery_date":today,"status":"IN_PROGRESS","delivery_order_ids":[]}])
    db.stock_transfers.insert_many([{"destination_branch_id":a,"status":"in_transit","receiving_status":"not_received"},{"destination_branch_id":b,"status":"in_transit","receiving_status":"not_received"}])
    result=branch_ops.get_branch_operations_overview(str(manager))
    assert result["kpis"]["deliveries_today"]==1 and result["kpis"]["incoming_stock"]==1
    assert len(result["board"]["in_progress"])==1

def test_tomorrow_summary_highlights_unplanned_and_transport_readiness(domain):
    db,a,b,manager,_=domain; tomorrow=(branch_ops.date.today()+branch_ops.timedelta(days=1)).isoformat(); agent=db.users.find_one({"full_name":"Accra Agent"})
    db.delivery_orders.insert_one({"_id":ObjectId(),"branch_id":a,"customer_name":"Tomorrow Unplanned","delivery_address":"Market","requested_delivery_date":tomorrow,"status":"CERTIFIED","assigned_field_agent_id":agent["_id"],"product_lines":[{"product_name":"Sofa"}]})
    result=branch_ops.get_branch_operations_overview(str(manager))
    assert result["kpis"]["tomorrow"]==1
    assert result["tomorrow_summary"]=={"total":1,"ready":0,"planning_required":1}
    assert result["board"]["awaiting_planning"][0]["readiness"]=="PLANNING_REQUIRED"
