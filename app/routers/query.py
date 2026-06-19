from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Order, FeeItem, OrderLog, OrderStatus
from app.schemas import OrderOut, FeeItemOut, OrderLogOut, FeeSummaryOut, OrderTimelineOut
from app.services.utils import enrich_order_dict, build_timeline

router = APIRouter(prefix="/query", tags=["用户查询"])


def _order_out(order) -> dict:
    return enrich_order_dict(order)


@router.get("/orders/{order_id}", response_model=OrderOut, summary="订单状态查询")
def get_order(order_id: int, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    return _order_out(order)


@router.get("/orders/by-no/{order_no}", response_model=OrderOut, summary="按订单号查询")
def get_order_by_no(order_no: str, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.order_no == order_no).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    return _order_out(order)


@router.get("/orders/by-phone/{phone}", response_model=list[OrderOut], summary="按手机号查询订单列表")
def get_orders_by_phone(phone: str, status: Optional[OrderStatus] = None, db: Session = Depends(get_db)):
    q = db.query(Order).filter(Order.user_phone == phone)
    if status:
        q = q.filter(Order.status == status)
    q = q.order_by(Order.created_at.desc())
    return [_order_out(o) for o in q.all()]


@router.get("/orders/{order_id}/fees", response_model=FeeSummaryOut, summary="费用明细查询")
def get_order_fees(order_id: int, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    items = db.query(FeeItem).filter(FeeItem.order_id == order_id).all()
    return FeeSummaryOut(
        order_id=order.id,
        order_no=order.order_no,
        base_fee=order.base_fee,
        extra_fee=order.extra_fee,
        discount_fee=order.discount_fee,
        total_fee=order.total_fee,
        fee_items=items,
    )


@router.get("/orders/{order_id}/logs", response_model=list[OrderLogOut], summary="订单操作日志")
def get_order_logs(order_id: int, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    return db.query(OrderLog).filter(OrderLog.order_id == order_id).order_by(OrderLog.created_at).all()


@router.get("/orders/{order_id}/timeline", response_model=OrderTimelineOut, summary="订单履约时间线")
def get_order_timeline(order_id: int, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    return build_timeline(order)
