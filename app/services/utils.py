from app.models import LockerSize, FeeType


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
