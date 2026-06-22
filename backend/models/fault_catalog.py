from bson import ObjectId


def _serialize_reference_id(value):
    if isinstance(value, ObjectId):
        return str(value)
    return value


def serialize_fault_category(category_document: dict) -> dict:
    return {
        "id": str(category_document.get("_id")),
        "name": category_document.get("name"),
        "code": category_document.get("code"),
        "status": category_document.get("status"),
        "created_by": _serialize_reference_id(category_document.get("created_by")),
        "updated_by": _serialize_reference_id(category_document.get("updated_by")),
        "created_at": category_document.get("created_at").isoformat()
        if category_document.get("created_at")
        else None,
        "updated_at": category_document.get("updated_at").isoformat()
        if category_document.get("updated_at")
        else None,
    }


def serialize_fault_component(component_document: dict) -> dict:
    return {
        "id": str(component_document.get("_id")),
        "category_id": _serialize_reference_id(component_document.get("category_id")),
        "name": component_document.get("name"),
        "code": component_document.get("code"),
        "status": component_document.get("status"),
        "created_by": _serialize_reference_id(component_document.get("created_by")),
        "updated_by": _serialize_reference_id(component_document.get("updated_by")),
        "created_at": component_document.get("created_at").isoformat()
        if component_document.get("created_at")
        else None,
        "updated_at": component_document.get("updated_at").isoformat()
        if component_document.get("updated_at")
        else None,
    }
