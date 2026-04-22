from flask import Blueprint, jsonify

from app.models import Warehouse

warehouses_bp = Blueprint("warehouses", __name__)


@warehouses_bp.route("", methods=["GET"])
def list_warehouses():
    whs = Warehouse.query.all()
    return jsonify([{"id": w.id, "name": w.name, "location": w.location} for w in whs])


@warehouses_bp.route("/<int:wh_id>/items", methods=["GET"])
def warehouse_items(wh_id: int):
    wh = Warehouse.query.get_or_404(wh_id)
    return jsonify([{"id": i.id, "sku": i.sku, "name": i.name} for i in wh.items])
