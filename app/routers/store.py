from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Order, FeeItem, Locker, OrderLog, OrderStatus, LockerStatus
from app.schemas import OrderOut, ConfirmReceivedRequest, UpdateWashingRequest, MarkReturnedRequest, SendPickupReminderRequest

router = APIRouter(prefix="/store", tags=["门店端"])


def _add_log(db: Session, order_id: int, action: str, detail: str = ""):
    log = OrderLog(order_id=order_id, action=action, detail=detail)
    db.add(log)


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
    total = 0.0
    for item in req.fee_items:
        amount = item.unit_price * item.quantity
        fee = FeeItem(
            order_id=order.id,
            item_name=item.item_name,
            unit_price=item.unit_price,
            quantity=item.quantity,
            amount=amount,
        )
        db.add(fee)
        total += amount
    order.total_fee = total
    _add_log(db, order.id, "received", f"门店确认收衣，费用录入{len(req.fee_items)}项，合计{total}元")
    db.commit()
    db.refresh(order)
    return order


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
    return order


@router.post("/orders/{order_id}/mark-returned", response_model=OrderOut, summary="标记已放回柜格")
def mark_returned(order_id: int, req: MarkReturnedRequest, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status != OrderStatus.done:
        raise HTTPException(status_code=400, detail="当前状态不可放回柜格，需先标记清洗完成")
    if order.locker_id:
        locker = db.query(Locker).filter(Locker.id == order.locker_id).first()
        if locker:
            if locker.status != LockerStatus.available:
                raise HTTPException(status_code=409, detail="原柜格不可用，请重新分配柜格")
            locker.status = LockerStatus.occupied
    order.status = OrderStatus.returned
    order.returned_at = datetime.utcnow()
    order.pickup_code = req.pickup_code
    _add_log(db, order.id, "returned", f"衣物已放回柜格，取件码: {req.pickup_code}")
    db.commit()
    db.refresh(order)
    return order


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
    return order


@router.post("/orders/{order_id}/send-pickup-reminder", summary="发送待取提醒")
def send_pickup_reminder(order_id: int, req: SendPickupReminderRequest, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status != OrderStatus.returned:
        raise HTTPException(status_code=400, detail="当前状态不可发送待取提醒")
    order.pickup_reminded = True
    msg = req.message or f"您的洗衣订单{order.order_no}已完成，请尽快取件，取件码:{order.pickup_code}"
    _add_log(db, order.id, "pickup_reminder", f"待取提醒已发送至{order.user_phone}: {msg}")
    db.commit()
    return {"order_id": order.id, "phone": order.user_phone, "message": msg, "sent": True}
