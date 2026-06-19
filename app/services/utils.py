from datetime import datetime
from app.models import LockerSize, FeeType, OrderStatus


SIZE_BASE_PRICE = {
    LockerSize.small: 29.0,
    LockerSize.medium: 49.0,
    LockerSize.large: 79.0,
}


def get_base_price(size: LockerSize) -> float:
    return SIZE_BASE_PRICE.get(size, 49.0)


def recalc_fees(order):
    base = 0.0
    extra = 0.0
    discount = 0.0
    for f in order.fee_items:
        if f.fee_type == FeeType.base:
            base += f.amount
        elif f.fee_type == FeeType.extra:
            extra += f.amount
        elif f.fee_type == FeeType.discount:
            discount += abs(f.amount)
    order.base_fee = round(base, 2)
    order.extra_fee = round(extra, 2)
    order.discount_fee = round(discount, 2)
    order.total_fee = round(max(0.0, base + extra - discount), 2)
    return order


def enrich_order_dict(order):
    data = {
        "id": order.id,
        "order_no": order.order_no,
        "user_phone": order.user_phone,
        "store_id": order.store_id,
        "locker_id": order.locker_id,
        "locker_no": order.locker.locker_no if order.locker else None,
        "drop_code": order.drop_code,
        "pickup_code": order.pickup_code,
        "status": order.status,
        "base_fee": order.base_fee,
        "extra_fee": order.extra_fee,
        "discount_fee": order.discount_fee,
        "total_fee": order.total_fee,
        "timeout_at": order.timeout_at,
        "pickup_reminded": order.pickup_reminded,
        "pickup_timeout_at": order.pickup_timeout_at,
        "created_at": order.created_at,
        "dropped_at": order.dropped_at,
        "received_at": order.received_at,
        "washing_at": order.washing_at,
        "done_at": order.done_at,
        "returned_at": order.returned_at,
        "picked_up_at": order.picked_up_at,
        "cancelled_at": order.cancelled_at,
    }
    return data


TIMELINE_NODES = [
    ("created", "订单创建", "created_at"),
    ("dropped", "用户投递", "dropped_at"),
    ("received", "门店收衣", "received_at"),
    ("washing", "清洗中", "washing_at"),
    ("done", "清洗完成", "done_at"),
    ("returned", "放回柜格", "returned_at"),
    ("reminded", "待取提醒", None),
    ("picked_up", "用户取件", "picked_up_at"),
]


def build_timeline(order):
    nodes = []
    reached = True
    node_set_done = set()
    for key, label, attr in TIMELINE_NODES:
        if key == "reminded":
            t = order.returned_at if order.pickup_reminded else None
            done = order.pickup_reminded
        else:
            t = getattr(order, attr) if attr else None
            done = t is not None
        nodes.append({
            "key": key,
            "label": label,
            "time": t,
            "done": done,
        })
        if key in ("created", "dropped", "received", "washing", "done", "returned", "picked_up"):
            if not done:
                reached = False
    return {
        "order_id": order.id,
        "order_no": order.order_no,
        "current_status": order.status,
        "nodes": nodes,
    }


def get_stuck_time(order):
    """返回订单在当前状态停留的分钟数"""
    status_time_map = {
        OrderStatus.created: "created_at",
        OrderStatus.dropped: "dropped_at",
        OrderStatus.received: "received_at",
        OrderStatus.washing: "washing_at",
        OrderStatus.done: "done_at",
        OrderStatus.returned: "returned_at",
    }
    attr = status_time_map.get(order.status)
    if not attr:
        return 0.0
    t = getattr(order, attr)
    if not t:
        return 0.0
    return (datetime.utcnow() - t).total_seconds() / 60.0
