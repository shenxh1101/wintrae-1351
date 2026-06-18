from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Order, FeeItem, OrderLog, OrderStatus
from app.schemas import OrderOut, FeeItemOut, OrderLogOut

router = APIRouter(prefix="/query", tags=["用户查询"])


@router.get("/orders/{order_id}", response_model=OrderOut, summary="订单状态查询")
def get_order(order_id: int, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    return order


@router.get("/orders/by-no/{order_no}", response_model=OrderOut, summary="按订单号查询")
def get_order_by_no(order_no: str, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.order_no == order_no).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    return order


@router.get("/orders/by-phone/{phone}", response_model=list[OrderOut], summary="按手机号查询订单列表")
def get_orders_by_phone(phone: str, status: Optional[OrderStatus] = None, db: Session = Depends(get_db)):
    q = db.query(Order).filter(Order.user_phone == phone)
    if status:
        q = q.filter(Order.status == status)
    q = q.order_by(Order.created_at.desc())
    return q.all()


@router.get("/orders/{order_id}/fees", response_model=list[FeeItemOut], summary="费用明细查询")
def get_order_fees(order_id: int, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    return db.query(FeeItem).filter(FeeItem.order_id == order_id).all()


@router.get("/orders/{order_id}/logs", response_model=list[OrderLogOut], summary="订单操作日志")
def get_order_logs(order_id: int, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    return db.query(OrderLog).filter(OrderLog.order_id == order_id).order_by(OrderLog.created_at).all()
