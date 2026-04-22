from app import db


class Warehouse(db.Model):
    __tablename__ = "warehouses"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    location = db.Column(db.String(200), nullable=False)

    items = db.relationship("Item", back_populates="warehouse")


class Item(db.Model):
    __tablename__ = "items"

    id = db.Column(db.Integer, primary_key=True)
    sku = db.Column(db.String(64), unique=True, nullable=False)
    name = db.Column(db.String(200), nullable=False)
    quantity = db.Column(db.Integer, default=0, nullable=False)
    warehouse_id = db.Column(
        db.Integer,
        db.ForeignKey("warehouses.id", ondelete="CASCADE"),
        nullable=False,
    )

    warehouse = db.relationship("Warehouse", back_populates="items")
