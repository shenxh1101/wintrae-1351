import enum
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, Enum, Text, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from app.database import Base


class LockerSize(str, enum.Enum):
    small = "small"
    medium = "medium"
    large = "large"


class LockerStatus(str, enum.Enum):
    available = "available"
    occupied = "occupied"
    maintenance = "maintenance"


class LockerAbnormalType(str, enum.Enum):
    fault = "fault"
    occupied_abnormal = "occupied_abnormal"


class OrderStatus(str, enum.Enum):
    created = "created"
    dropped = "dropped"
    received = "received"
    washing = "washing"
    done = "done"
    returned = "returned"
    picked_up = "picked_up"
    cancelled = "cancelled"
    timeout = "timeout"


class FeeType(str, enum.Enum):
    base = "base"
    extra = "extra"
    discount = "discount"


class RetentionStatus(str, enum.Enum):
    pending = "pending"
    resolved = "resolved"


class Store(Base):
    __tablename__ = "stores"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    address = Column(String(300), nullable=False)
    phone = Column(String(20), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    lockers = relationship("Locker", back_populates="store")
    orders = relationship("Order", back_populates="store")


class Locker(Base):
    __tablename__ = "lockers"

    id = Column(Integer, primary_key=True, index=True)
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=False)
    locker_no = Column(String(20), nullable=False)
    size = Column(Enum(LockerSize), nullable=False, default=LockerSize.medium)
    status = Column(Enum(LockerStatus), nullable=False, default=LockerStatus.available)
    is_abnormal = Column(Boolean, default=False, nullable=False)
    abnormal_type = Column(Enum(LockerAbnormalType), nullable=True)
    abnormal_note = Column(String(300), nullable=True)
    abnormal_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    store = relationship("Store", back_populates="lockers")
    orders = relationship("Order", back_populates="locker")


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    order_no = Column(String(32), unique=True, nullable=False, index=True)
    user_phone = Column(String(20), nullable=False)
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=False)
    locker_id = Column(Integer, ForeignKey("lockers.id"), nullable=True)
    drop_code = Column(String(8), nullable=True)
    pickup_code = Column(String(8), nullable=True)
    status = Column(Enum(OrderStatus), nullable=False, default=OrderStatus.created)
    base_fee = Column(Float, default=0.0)
    extra_fee = Column(Float, default=0.0)
    discount_fee = Column(Float, default=0.0)
    total_fee = Column(Float, default=0.0)
    timeout_at = Column(DateTime, nullable=True)
    pickup_reminded = Column(Boolean, default=False, nullable=False)
    pickup_timeout_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    dropped_at = Column(DateTime, nullable=True)
    received_at = Column(DateTime, nullable=True)
    washing_at = Column(DateTime, nullable=True)
    done_at = Column(DateTime, nullable=True)
    returned_at = Column(DateTime, nullable=True)
    picked_up_at = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)

    store = relationship("Store", back_populates="orders")
    locker = relationship("Locker", back_populates="orders")
    fee_items = relationship("FeeItem", back_populates="order", cascade="all, delete-orphan")
    logs = relationship("OrderLog", back_populates="order", cascade="all, delete-orphan")
    retentions = relationship("RetentionRecord", back_populates="order", cascade="all, delete-orphan")


class FeeItem(Base):
    __tablename__ = "fee_items"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    fee_type = Column(Enum(FeeType), nullable=False, default=FeeType.extra)
    item_name = Column(String(100), nullable=False)
    unit_price = Column(Float, nullable=False)
    quantity = Column(Integer, nullable=False, default=1)
    amount = Column(Float, nullable=False)

    order = relationship("Order", back_populates="fee_items")


class OrderLog(Base):
    __tablename__ = "order_logs"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    action = Column(String(50), nullable=False)
    detail = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    order = relationship("Order", back_populates="logs")


class RetentionRecord(Base):
    __tablename__ = "retention_records"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    locker_id = Column(Integer, ForeignKey("lockers.id"), nullable=False)
    overdue_hours = Column(Float, nullable=False, default=0.0)
    status = Column(Enum(RetentionStatus), nullable=False, default=RetentionStatus.pending)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)

    order = relationship("Order", back_populates="retentions")
