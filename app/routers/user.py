from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Store, Locker, Order, OrderLog, LockerSize, LockerStatus, OrderStatus, FeeType
from app.schemas import (
    StoreOut, LockerOut, OrderCreate, OrderOut, FeeItemOut,
    PhoneUpdate, TimeoutHandleResult,
)
from app.init_db import generate_order_no, generate_code
from app.services.utils import enrich_order_dict, get_base_price

router = APIRouter(prefix="/user", tags=["用户端"])

DROP_TIMEOUT_HOURS = 2


def _add_log(db: Session, order_id: int, action: str, detail: str = ""):
    db.add(OrderLog(order_id=order_id, action=action, detail=detail))


def _order_out(order) -> dict:
    return enrich_order_dict(order)


@router.get("/stores", response_model=list[StoreOut], summary="门店查询")
def list_stores(is_active: Optional[bool] = True, db: Session = Depends(get_db)):
    q = db.query(Store)
    if is_active is not None:
        q = q.filter(Store.is_active == is_active)
    return q.all()


@router.get("/stores/{store_id}", response_model=StoreOut, summary="门店详情")
def get_store(store_id: int, db: Session = Depends(get_db)):
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="门店不存在")
    return store


@router.get("/lockers/available", response_model=list[LockerOut], summary="可用柜格查询")
def available_lockers(store_id: int, size: Optional[LockerSize] = None, db: Session = Depends(get_db)):
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="门店不存在")
    q = db.query(Locker).filter(
        Locker.store_id == store_id,
        Locker.status == LockerStatus.available,
        Locker.is_abnormal == False,
    )
    if size:
        q = q.filter(Locker.size == size)
    return q.all()


@router.post("/orders", response_model=OrderOut, summary="创建洗衣订单")
def create_order(req: OrderCreate, db: Session = Depends(get_db)):
    store = db.query(Store).filter(Store.id == req.store_id, Store.is_active == True).first()
    if not store:
        raise HTTPException(status_code=404, detail="门店不存在或已停用")
    locker = db.query(Locker).filter(
        Locker.store_id == req.store_id,
        Locker.size == req.locker_size,
        Locker.status == LockerStatus.available,
        Locker.is_abnormal == False,
    ).with_for_update().first()
    if not locker:
        raise HTTPException(status_code=409, detail="该门店无可用柜格")
    locker.status = LockerStatus.occupied
    order = Order(
        order_no=generate_order_no(),
        user_phone=req.user_phone,
        store_id=req.store_id,
        locker_id=locker.id,
        drop_code=generate_code(6),
        status=OrderStatus.created,
        timeout_at=datetime.utcnow() + timedelta(hours=DROP_TIMEOUT_HOURS),
    )
    db.add(order)
    db.flush()
    _add_log(db, order.id, "order_created", f"订单创建，分配柜格{locker.locker_no}")
    db.commit()
    db.refresh(order)
    return _order_out(order)


@router.post("/orders/{order_id}/assign-locker", response_model=OrderOut, summary="分配柜格")
def assign_locker(order_id: int, locker_size: Optional[LockerSize] = None, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status != OrderStatus.created:
        raise HTTPException(status_code=400, detail="当前订单状态不可分配柜格")
    if order.locker_id:
        raise HTTPException(status_code=400, detail="订单已分配柜格")
    target_size = locker_size or LockerSize.medium
    locker = db.query(Locker).filter(
        Locker.store_id == order.store_id,
        Locker.size == target_size,
        Locker.status == LockerStatus.available,
        Locker.is_abnormal == False,
    ).with_for_update().first()
    if not locker:
        raise HTTPException(status_code=409, detail="无可用柜格")
    locker.status = LockerStatus.occupied
    order.locker_id = locker.id
    order.timeout_at = datetime.utcnow() + timedelta(hours=DROP_TIMEOUT_HOURS)
    _add_log(db, order.id, "locker_assigned", f"分配柜格{locker.locker_no}")
    db.commit()
    db.refresh(order)
    return _order_out(order)


@router.post("/orders/{order_id}/drop-code", response_model=OrderOut, summary="生成投递码")
def generate_drop_code(order_id: int, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status != OrderStatus.created:
        raise HTTPException(status_code=400, detail="当前状态不可生成投递码")
    if not order.locker_id:
        raise HTTPException(status_code=400, detail="请先分配柜格")
    if not order.drop_code:
        order.drop_code = generate_code(6)
        _add_log(db, order.id, "drop_code_generated", f"投递码已生成: {order.drop_code}")
    db.commit()
    db.refresh(order)
    return _order_out(order)


@router.post("/orders/{order_id}/confirm-drop", response_model=OrderOut, summary="确认投递（用户输入投递码）")
def confirm_drop(order_id: int, drop_code: str, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status != OrderStatus.created:
        raise HTTPException(status_code=400, detail="当前状态不可投递")
    if order.drop_code != drop_code:
        raise HTTPException(status_code=400, detail="投递码错误")
    order.status = OrderStatus.dropped
    order.dropped_at = datetime.utcnow()
    _add_log(db, order.id, "dropped", "用户已投递衣物到柜")
    db.commit()
    db.refresh(order)
    return _order_out(order)


@router.post("/orders/{order_id}/record-pickup-code", response_model=OrderOut, summary="记录取件码")
def record_pickup_code(order_id: int, pickup_code: str, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status not in (OrderStatus.returned,):
        raise HTTPException(status_code=400, detail="当前状态不可记录取件码")
    order.pickup_code = pickup_code
    _add_log(db, order.id, "pickup_code_recorded", f"取件码已记录: {pickup_code}")
    db.commit()
    db.refresh(order)
    return _order_out(order)


@router.post("/orders/{order_id}/confirm-pickup", response_model=OrderOut, summary="确认取件（用户输入取件码）")
def confirm_pickup(order_id: int, pickup_code: str, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status != OrderStatus.returned:
        raise HTTPException(status_code=400, detail="当前状态不可取件")
    if order.pickup_code != pickup_code:
        raise HTTPException(status_code=400, detail="取件码错误")
    order.status = OrderStatus.picked_up
    order.picked_up_at = datetime.utcnow()
    if order.locker_id:
        locker = db.query(Locker).filter(Locker.id == order.locker_id).first()
        if locker:
            locker.status = LockerStatus.available
    _add_log(db, order.id, "picked_up", "用户已取件，柜格释放")
    db.commit()
    db.refresh(order)
    return _order_out(order)


@router.get("/orders/{order_id}/estimate-fee", summary="计算预估费用")
def estimate_fee(order_id: int, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.locker_id:
        locker = db.query(Locker).filter(Locker.id == order.locker_id).first()
        size = locker.size if locker else LockerSize.medium
    else:
        size = LockerSize.medium
    base_fee = get_base_price(size)
    extra_fee = 0.0
    discount_fee = 0.0
    for f in order.fee_items:
        if f.fee_type == FeeType.extra:
            extra_fee += f.amount
        elif f.fee_type == FeeType.discount:
            discount_fee += abs(f.amount)
    total = max(0.0, base_fee + extra_fee - discount_fee)
    return {
        "order_id": order.id,
        "order_no": order.order_no,
        "locker_size": size.value,
        "base_fee": base_fee,
        "extra_fee": round(extra_fee, 2),
        "discount_fee": round(discount_fee, 2),
        "estimated_total": round(total, 2),
    }


@router.post("/orders/timeout-handle", response_model=TimeoutHandleResult, summary="处理超时占柜")
def handle_timeout_orders(db: Session = Depends(get_db)):
    now = datetime.utcnow()
    timeout_orders = db.query(Order).filter(
        Order.status == OrderStatus.created,
        Order.timeout_at != None,
        Order.timeout_at < now,
    ).all()
    processed = []
    for order in timeout_orders:
        order.status = OrderStatus.timeout
        order.cancelled_at = now
        if order.locker_id:
            locker = db.query(Locker).filter(Locker.id == order.locker_id).first()
            if locker:
                locker.status = LockerStatus.available
        _add_log(db, order.id, "timeout", "超时未投递，订单自动取消，柜格释放")
        processed.append(order.id)
    db.commit()
    return TimeoutHandleResult(processed_count=len(processed), timeout_order_ids=processed)


@router.post("/orders/{order_id}/cancel", response_model=OrderOut, summary="取消订单")
def cancel_order(order_id: int, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status not in (OrderStatus.created, OrderStatus.dropped):
        raise HTTPException(status_code=400, detail="当前状态不可取消订单")
    order.status = OrderStatus.cancelled
    order.cancelled_at = datetime.utcnow()
    if order.locker_id:
        locker = db.query(Locker).filter(Locker.id == order.locker_id).first()
        if locker:
            locker.status = LockerStatus.available
    _add_log(db, order.id, "cancelled", "订单已取消，柜格释放")
    db.commit()
    db.refresh(order)
    return _order_out(order)


@router.patch("/orders/{order_id}/phone", response_model=OrderOut, summary="修改联系电话")
def update_phone(order_id: int, req: PhoneUpdate, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    old_phone = order.user_phone
    order.user_phone = req.user_phone
    _add_log(db, order.id, "phone_updated", f"联系电话从{old_phone}修改为{req.user_phone}")
    db.commit()
    db.refresh(order)
    return _order_out(order)
