from datetime import datetime, date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Store, Locker, Order, OrderStatus
from app.schemas import StoreOrderSummaryOut, LockerAbnormalOut, DailyCompletionOut

router = APIRouter(prefix="/admin", tags=["管理端"])


@router.get("/store-order-summary", response_model=list[StoreOrderSummaryOut], summary="门店订单汇总")
def store_order_summary(
    store_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = db.query(Order)
    if store_id:
        q = q.filter(Order.store_id == store_id)
    if start_date:
        sd = datetime.strptime(start_date, "%Y-%m-%d")
        q = q.filter(Order.created_at >= sd)
    if end_date:
        ed = datetime.strptime(end_date, "%Y-%m-%d") + __import__("datetime").timedelta(days=1)
        q = q.filter(Order.created_at < ed)
    orders = q.all()
    store_map = {}
    for s in db.query(Store).all():
        store_map[s.id] = s.name
    grouped = {}
    for o in orders:
        if o.store_id not in grouped:
            grouped[o.store_id] = {
                "store_id": o.store_id,
                "store_name": store_map.get(o.store_id, ""),
                "total_orders": 0,
                "created_count": 0,
                "washing_count": 0,
                "done_count": 0,
                "returned_count": 0,
                "picked_up_count": 0,
                "cancelled_count": 0,
                "total_fee": 0.0,
            }
        g = grouped[o.store_id]
        g["total_orders"] += 1
        status_map = {
            OrderStatus.created: "created_count",
            OrderStatus.dropped: "created_count",
            OrderStatus.received: "washing_count",
            OrderStatus.washing: "washing_count",
            OrderStatus.done: "done_count",
            OrderStatus.returned: "returned_count",
            OrderStatus.picked_up: "picked_up_count",
            OrderStatus.cancelled: "cancelled_count",
            OrderStatus.timeout: "cancelled_count",
        }
        key = status_map.get(o.status)
        if key:
            g[key] += 1
        if o.status == OrderStatus.picked_up:
            g["total_fee"] += o.total_fee
    return list(grouped.values())


@router.get("/abnormal-lockers", response_model=list[LockerAbnormalOut], summary="异常柜格列表")
def abnormal_lockers(store_id: Optional[int] = None, db: Session = Depends(get_db)):
    q = db.query(Locker).filter(Locker.is_abnormal == True)
    if store_id:
        q = q.filter(Locker.store_id == store_id)
    return q.all()


@router.get("/daily-completion", response_model=list[DailyCompletionOut], summary="每日取送完成情况")
def daily_completion(
    target_date: Optional[str] = Query(None, description="日期格式YYYY-MM-DD，默认今天"),
    store_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    if target_date:
        d = datetime.strptime(target_date, "%Y-%m-%d").date()
    else:
        d = date.today()
    day_start = datetime.combine(d, datetime.min.time())
    day_end = datetime.combine(d, datetime.max.time())
    store_map = {}
    for s in db.query(Store).all():
        store_map[s.id] = s.name
    stores_q = db.query(Store)
    if store_id:
        stores_q = stores_q.filter(Store.id == store_id)
    stores = stores_q.all()
    result = []
    for s in stores:
        dropped_count = db.query(func.count(Order.id)).filter(
            Order.store_id == s.id,
            Order.dropped_at >= day_start,
            Order.dropped_at <= day_end,
        ).scalar() or 0
        picked_up_count = db.query(func.count(Order.id)).filter(
            Order.store_id == s.id,
            Order.picked_up_at >= day_start,
            Order.picked_up_at <= day_end,
        ).scalar() or 0
        result.append(DailyCompletionOut(
            store_id=s.id,
            store_name=s.name,
            dropped_count=dropped_count,
            picked_up_count=picked_up_count,
            date=d.isoformat(),
        ))
    return result
