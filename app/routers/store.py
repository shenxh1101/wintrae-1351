from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import (
    Order, FeeItem, Locker, OrderLog, OrderStatus, LockerStatus,
    LockerAbnormalType, FeeType, LockerSize,
)
from app.schemas import (
    OrderOut, ConfirmReceivedRequest, UpdateWashingRequest,
    MarkReturnedRequest, SendPickupReminderRequest,
    MarkLockerAbnormalRequest, LockerRestoreRequest,
    LockerOut, FeeItemCreate, FeeItemUpdate, FeeItemOut,
)
from app.services.utils import enrich_order_dict, recalc_fees, get_base_price
from app.init_db import generate_code

PICKUP_TIMEOUT_HOURS = 24

router = APIRouter(prefix="/store", tags=["门店端"])


def _add_log(db: Session, order_id: int, action: str, detail: str = ""):
    db.add(OrderLog(order_id=order_id, action=action, detail=detail))


def _order_out(order) -> dict:
    return enrich_order_dict(order)


@router.post("/orders/{order_id}/confirm-received", response_model=OrderOut, summary="确认收衣")
def confirm_received(order_id: int, req: ConfirmReceivedRequest, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status != OrderStatus.dropped:
        raise HTTPException(status_code=400, detail="当前状态不可确认收衣")
    order.status = OrderStatus.received
    order.received_at = datetime.utcnow()
    if order.locker_id:
        locker = db.query(Locker).filter(Locker.id == order.locker_id).first()
        if locker:
            locker.status = LockerStatus.available
    size = LockerSize.medium
    if order.locker_id:
        locker = db.query(Locker).filter(Locker.id == order.locker_id).first()
        if locker:
            size = locker.size
    base_price = get_base_price(size)
    has_base = any(f.fee_type == FeeType.base for f in req.fee_items)
    if not has_base:
        db.add(FeeItem(
            order_id=order.id, fee_type=FeeType.base,
            item_name=f"柜格基础服务费({size.value})",
            unit_price=base_price, quantity=1, amount=base_price,
        ))
    for item in req.fee_items:
        amount = item.unit_price * item.quantity
        sign = -1 if item.fee_type == FeeType.discount else 1
        db.add(FeeItem(
            order_id=order.id, fee_type=item.fee_type,
            item_name=item.item_name, unit_price=item.unit_price,
            quantity=item.quantity, amount=sign * abs(amount),
        ))
    db.flush()
    recalc_fees(order)
    _add_log(db, order.id, "received", f"门店确认收衣，费用{len(req.fee_items)}项，合计{order.total_fee}元")
    db.commit()
    db.refresh(order)
    return _order_out(order)


@router.post("/orders/{order_id}/update-washing", response_model=OrderOut, summary="更新清洗进度")
def update_washing(order_id: int, req: UpdateWashingRequest, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status not in (OrderStatus.received, OrderStatus.washing):
        raise HTTPException(status_code=400, detail="当前状态不可更新清洗进度")
    if order.status == OrderStatus.received:
        order.status = OrderStatus.washing
        order.washing_at = datetime.utcnow()
    _add_log(db, order.id, "washing_progress", req.progress_note or "清洗进度更新")
    db.commit()
    db.refresh(order)
    return _order_out(order)


@router.post("/orders/{order_id}/mark-done", response_model=OrderOut, summary="标记清洗完成")
def mark_done(order_id: int, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status != OrderStatus.washing:
        raise HTTPException(status_code=400, detail="当前状态不可标记清洗完成")
    order.status = OrderStatus.done
    order.done_at = datetime.utcnow()
    _add_log(db, order.id, "done", "清洗完成，待放回柜格")
    db.commit()
    db.refresh(order)
    return _order_out(order)


@router.post("/orders/{order_id}/mark-returned", response_model=OrderOut, summary="标记已放回柜格")
def mark_returned(order_id: int, req: MarkReturnedRequest, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status != OrderStatus.done:
        raise HTTPException(status_code=400, detail="当前状态不可放回柜格，需先标记清洗完成")

    target_locker_id = req.locker_id or order.locker_id
    if not target_locker_id:
        raise HTTPException(status_code=400, detail="缺少柜格信息")

    target = db.query(Locker).filter(
        Locker.id == target_locker_id, Locker.store_id == order.store_id,
    ).first()
    if not target:
        raise HTTPException(status_code=404, detail="柜格不存在或不属于该门店")
    if target.is_abnormal:
        raise HTTPException(status_code=409, detail=f"柜格{target.locker_no}处于异常状态，不可使用")
    if target.status != LockerStatus.available:
        alt = db.query(Locker).filter(
            Locker.store_id == order.store_id,
            Locker.status == LockerStatus.available,
            Locker.is_abnormal == False,
        ).first()
        if not alt:
            raise HTTPException(status_code=409, detail="无可用柜格，请稍后再试")
        target = alt

    if order.locker_id and order.locker_id != target.id:
        old = db.query(Locker).filter(Locker.id == order.locker_id).first()
        if old and old.status == LockerStatus.occupied:
            old.status = LockerStatus.available
    target.status = LockerStatus.occupied
    order.locker_id = target.id
    order.status = OrderStatus.returned
    order.returned_at = datetime.utcnow()
    order.pickup_code = req.pickup_code
    order.pickup_timeout_at = datetime.utcnow() + timedelta(hours=PICKUP_TIMEOUT_HOURS)
    _add_log(db, order.id, "returned", f"衣物已放回柜格{target.locker_no}，取件码:{req.pickup_code}")
    db.commit()
    db.refresh(order)
    return _order_out(order)


@router.post("/orders/{order_id}/send-pickup-reminder", summary="发送待取提醒")
def send_pickup_reminder(order_id: int, req: SendPickupReminderRequest, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status != OrderStatus.returned:
        raise HTTPException(status_code=400, detail="当前状态不可发送待取提醒")
    order.pickup_reminded = True
    locker_no = order.locker.locker_no if order.locker else ""
    msg = req.message or f"您的洗衣订单{order.order_no}已完成，柜格{locker_no}，取件码:{order.pickup_code}"
    _add_log(db, order.id, "pickup_reminder", f"待取提醒已发送至{order.user_phone}: {msg}")
    db.commit()
    return {"order_id": order.id, "phone": order.user_phone, "locker_no": locker_no, "pickup_code": order.pickup_code, "message": msg, "sent": True}


@router.post("/lockers/{locker_id}/mark-abnormal", response_model=LockerOut, summary="将柜格标记为异常")
def mark_locker_abnormal(locker_id: int, req: MarkLockerAbnormalRequest, db: Session = Depends(get_db)):
    locker = db.query(Locker).filter(Locker.id == locker_id).first()
    if not locker:
        raise HTTPException(status_code=404, detail="柜格不存在")
    locker.is_abnormal = True
    locker.abnormal_type = req.abnormal_type
    locker.abnormal_note = req.note
    locker.abnormal_at = datetime.utcnow()
    if req.abnormal_type == LockerAbnormalType.fault:
        locker.status = LockerStatus.maintenance
    db.commit()
    db.refresh(locker)
    return locker


@router.post("/lockers/{locker_id}/restore", summary="恢复柜格可用")
def restore_locker(locker_id: int, req: LockerRestoreRequest, db: Session = Depends(get_db)):
    locker = db.query(Locker).filter(Locker.id == locker_id).first()
    if not locker:
        raise HTTPException(status_code=404, detail="柜格不存在")
    if not locker.is_abnormal:
        raise HTTPException(status_code=400, detail="柜格当前无异常，无需恢复")
    pending_order = (
        db.query(Order)
        .filter(
            Order.locker_id == locker.id,
            Order.status.in_([
                OrderStatus.created, OrderStatus.dropped,
                OrderStatus.received, OrderStatus.washing,
                OrderStatus.done, OrderStatus.returned,
            ]),
        )
        .order_by(Order.created_at.desc())
        .first()
    )
    if pending_order:
        return {
            "ok": False,
            "locker_id": locker.id,
            "locker_no": locker.locker_no,
            "reason": "柜格内有未完成订单，暂不可恢复",
            "order_id": pending_order.id,
            "order_no": pending_order.order_no,
            "order_status": pending_order.status,
            "user_phone": pending_order.user_phone,
        }
    old_type = locker.abnormal_type
    locker.is_abnormal = False
    locker.abnormal_type = None
    if locker.status == LockerStatus.maintenance:
        locker.status = LockerStatus.available
    if req.note:
        locker.abnormal_note = (locker.abnormal_note or "") + f" | 恢复备注: {req.note}"
    db.commit()
    db.refresh(locker)
    return {
        "ok": True,
        "locker_id": locker.id,
        "locker_no": locker.locker_no,
        "status": locker.status,
        "is_abnormal": locker.is_abnormal,
        "old_abnormal_type": old_type,
    }


@router.post("/orders/{order_id}/fees", response_model=FeeItemOut, summary="追加费用明细")
def add_fee_item(order_id: int, req: FeeItemCreate, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status in (OrderStatus.picked_up, OrderStatus.cancelled, OrderStatus.timeout):
        raise HTTPException(status_code=400, detail="当前订单状态不可修改费用")
    amount = req.unit_price * req.quantity
    sign = -1 if req.fee_type == FeeType.discount else 1
    fee = FeeItem(
        order_id=order.id, fee_type=req.fee_type, item_name=req.item_name,
        unit_price=req.unit_price, quantity=req.quantity, amount=sign * abs(amount),
    )
    db.add(fee)
    db.flush()
    recalc_fees(order)
    _add_log(db, order.id, "fee_added", f"追加费用: {req.item_name} {amount}元")
    db.commit()
    db.refresh(fee)
    return fee


@router.put("/orders/fees/{fee_id}", response_model=FeeItemOut, summary="修改费用明细")
def update_fee_item(fee_id: int, req: FeeItemUpdate, db: Session = Depends(get_db)):
    fee = db.query(FeeItem).filter(FeeItem.id == fee_id).first()
    if not fee:
        raise HTTPException(status_code=404, detail="费用明细不存在")
    order = db.query(Order).filter(Order.id == fee.order_id).first()
    if order.status in (OrderStatus.picked_up, OrderStatus.cancelled, OrderStatus.timeout):
        raise HTTPException(status_code=400, detail="当前订单状态不可修改费用")
    if req.fee_type is not None:
        fee.fee_type = req.fee_type
    if req.item_name is not None:
        fee.item_name = req.item_name
    if req.unit_price is not None:
        fee.unit_price = req.unit_price
    if req.quantity is not None:
        fee.quantity = req.quantity
    amount = fee.unit_price * fee.quantity
    sign = -1 if fee.fee_type == FeeType.discount else 1
    fee.amount = sign * abs(amount)
    db.flush()
    recalc_fees(order)
    _add_log(db, order.id, "fee_updated", f"修改费用项#{fee_id}: {fee.item_name} {fee.amount}元")
    db.commit()
    db.refresh(fee)
    return fee


@router.delete("/orders/fees/{fee_id}", summary="删除费用明细")
def delete_fee_item(fee_id: int, db: Session = Depends(get_db)):
    fee = db.query(FeeItem).filter(FeeItem.id == fee_id).first()
    if not fee:
        raise HTTPException(status_code=404, detail="费用明细不存在")
    order = db.query(Order).filter(Order.id == fee.order_id).first()
    if order.status in (OrderStatus.picked_up, OrderStatus.cancelled, OrderStatus.timeout):
        raise HTTPException(status_code=400, detail="当前订单状态不可修改费用")
    name = fee.item_name
    db.delete(fee)
    db.flush()
    recalc_fees(order)
    _add_log(db, order.id, "fee_deleted", f"删除费用项: {name}")
    db.commit()
    return {"ok": True, "deleted_id": fee_id}
