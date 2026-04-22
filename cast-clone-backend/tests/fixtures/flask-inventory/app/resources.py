from flask import request
from flask_restful import Resource, abort

from app import db
from app.models import Item


class ItemListResource(Resource):
    def get(self):
        items = Item.query.all()
        return [{"id": i.id, "sku": i.sku, "name": i.name, "quantity": i.quantity} for i in items]

    def post(self):
        data = request.json or {}
        item = Item(
            sku=data["sku"],
            name=data["name"],
            quantity=data.get("quantity", 0),
            warehouse_id=data["warehouse_id"],
        )
        db.session.add(item)
        db.session.commit()
        return {"id": item.id}, 201


class ItemResource(Resource):
    def get(self, item_id: int):
        item = db.session.get(Item, item_id) or abort(404, message="item not found")
        return {"id": item.id, "sku": item.sku, "name": item.name, "quantity": item.quantity}

    def delete(self, item_id: int):
        item = db.session.get(Item, item_id) or abort(404, message="item not found")
        db.session.delete(item)
        db.session.commit()
        return "", 204
