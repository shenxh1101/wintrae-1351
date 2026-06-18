from datetime import datetime, date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Store, Locker, Order, OrderStatus, RetentionRecord, RetentionStatus
from app.schemas import (
    StoreOrderSummaryOut, LockerAbnormalOut, DailyCompletionOut,
    RetentionRecordOut, RetentionHandleResult, RetentionResolveRequest,
)

router = APIRouter(prefix="/admin", tags=["管理端"])


@router.get("/store-order-summary", response_model=list[StoreOrderSummaryOut], summary="门店订单汇总")
def store_order_summary(
    store_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db),
):
    import datetime as _dt
    q = db.query(Order)
    if store_id:
        q = q.filter(Order.store_id == store_id)
    if start_date:
        sd = datetime.strptime(start_date, "%Y-%m-%d")
        q = q.filter(Order.created_at >= sd)
    if end_date:
        ed = datetime.strptime(end_date, "%Y-%m-%d") + _dt.timedelta(days=1)
        q = q.filter(Order.created_at < ed)
    orders = q.all()
    store_map = {s.id: s.name for s in db.query(Store).all()}
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
    lockers = q.all()
    result = []
    store_map = {s.id: s.name for s in db.query(Store).all()}
    for lk in lockers:
        last_order = (
            db.query(Order)
            .filter(Order.locker_id == lk.id)
            .order_by(Order.created_at.desc())
            .first()
        )
        result.append(LockerAbnormalOut(
            id=lk.id,
            store_id=lk.store_id,
            store_name=store_map.get(lk.store_id),
            locker_no=lk.locker_no,
            size=lk.size,
            status=lk.status,
            is_abnormal=lk.is_abnormal,
            abnormal_type=lk.abnormal_type,
            abnormal_note=lk.abnormal_note,
            abnormal_at=lk.abnormal_at,
            last_order_no=last_order.order_no if last_order else None,
            last_order_status=last_order.status if last_order else None,
        ))
    return result


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
        timeout_cancelled_count = db.query(func.count(Order.id)).filter(
            Order.store_id == s.id,
            Order.cancelled_at >= day_start,
            Order.cancelled_at <= day_end,
            Order.status.in_([OrderStatus.timeout, OrderStatus.cancelled]),
        ).scalar() or 0
        abnormal_locker_count = db.query(func.count(Locker.id)).filter(
            Locker.store_id == s.id,
            Locker.is_abnormal == True,
        ).scalar() or 0
        retention_count = db.query(func.count(RetentionRecord.id)).join(
            Order, RetentionRecord.order_id == Order.id
        ).filter(
            Order.store_id == s.id,
            RetentionRecord.created_at >= day_start,
            RetentionRecord.created_at <= day_end,
        ).scalar() or 0
        result.append(DailyCompletionOut(
            store_id=s.id,
            store_name=s.name,
            dropped_count=dropped_count,
            picked_up_count=picked_up_count,
            timeout_cancelled_count=timeout_cancelled_count,
            abnormal_locker_count=abnormal_locker_count,
            retention_count=retention_count,
            date=d.isoformat(),
        ))
    return result


@router.post("/retentions/generate", response_model=RetentionHandleResult, summary="生成滞留记录（待取超时）")
def generate_retentions(db: Session = Depends(get_db)):
    now = datetime.utcnow()
    overdue = db.query(Order).filter(
        Order.status == OrderStatus.returned,
        Order.pickup_timeout_at != None,
        Order.pickup_timeout_at < now,
    ).all()
    ids = []
    for order in overdue:
        existing = db.query(RetentionRecord).filter(
            RetentionRecord.order_id == order.id,
            RetentionRecord.status == RetentionStatus.pending,
        ).first()
        if existing:
            continue
        hours = (now - order.pickup_timeout_at).total_seconds() / 3600.0
        rec = RetentionRecord(
            order_id=order.id,
            locker_id=order.locker_id,
            overdue_hours=round(hours, 2),
            status=RetentionStatus.pending,
            note="取件超时，自动生成滞留记录",
        )
        db.add(rec)
        db.flush()
        ids.append(rec.id)
    db.commit()
    return RetentionHandleResult(processed_count=len(ids), generated_retention_ids=ids)


@router.get("/retentions", response_model=list[RetentionRecordOut], summary="滞留记录列表")
def list_retentions(
    status: Optional[RetentionStatus] = None,
    store_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    q = db.query(RetentionRecord)
    if status:
        q = q.filter(RetentionRecord.status == status)
    if store_id:
        q = q.join(Order, RetentionRecord.order_id == Order.id).filter(Order.store_id == store_id)
    records = q.order_by(RetentionRecord.created_at.desc()).all()
    out = []
    for r in records:
        out.append(RetentionRecordOut(
            id=r.id,
            order_id=r.order_id,
            order_no=r.order.order_no if r.order else None,
            locker_id=r.locker_id,
            locker_no=r.order.locker.locker_no if (r.order and r.order.locker) else None,
            overdue_hours=r.overdue_hours,
            status=r.status,
            note=r.note,
            created_at=r.created_at,
            resolved_at=r.resolved_at,
        ))
    return out


@router.post("/retentions/{retention_id}/resolve", response_model=RetentionRecordOut, summary="解决滞留记录")
def resolve_retention(retention_id: int, req: RetentionResolveRequest, db: Session = Depends(get_db)):
    rec = db.query(RetentionRecord).filter(RetentionRecord.id == retention_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="滞留记录不存在")
    rec.status = RetentionStatus.resolved
    rec.resolved_at = datetime.utcnow()
    if req.note:
        rec.note = (rec.note or "") + f" | 解决备注: {req.note}"
    db.commit()
    db.refresh(rec)
    return RetentionRecordOut(
        id=rec.id,
        order_id=rec.order_id,
        order_no=rec.order.order_no if rec.order else None,
        locker_id=rec.locker_id,
        locker_no=rec.order.locker.locker_no if (rec.order and rec.order.locker) else None,
        overdue_hours=rec.overdue_hours,
        status=rec.status,
        note=rec.note,
        created_at=rec.created_at,
        resolved_at=rec.resolved_at,
    )
