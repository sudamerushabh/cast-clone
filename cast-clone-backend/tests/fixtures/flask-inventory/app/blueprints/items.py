from flask import Blueprint, jsonify, request

from app import db
from app.models import Item

items_bp = Blueprint("items", __name__)


@items_bp.route("", methods=["GET"])
def list_items():
    items = Item.query.all()
    return jsonify([{"id": i.id, "sku": i.sku, "name": i.name, "quantity": i.quantity} for i in items])


@items_bp.route("/<int:item_id>/adjust", methods=["POST"])
def adjust_quantity(item_id: int):
    delta = int(request.json.get("delta", 0))
    item = db.session.get(Item, item_id)
    if item is None:
        return jsonify({"error": "not found"}), 404
    item.quantity += delta
    db.session.commit()
    return jsonify({"id": item.id, "quantity": item.quantity})
