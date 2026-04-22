from flask import Flask
from flask_restful import Api
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///inventory.db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)

    from app.blueprints.items import items_bp
    from app.blueprints.warehouses import warehouses_bp
    from app.resources import ItemResource, ItemListResource

    app.register_blueprint(items_bp, url_prefix="/items")
    app.register_blueprint(warehouses_bp, url_prefix="/warehouses")

    api = Api(app, prefix="/api")
    api.add_resource(ItemListResource, "/items")
    api.add_resource(ItemResource, "/items/<int:item_id>")

    return app
