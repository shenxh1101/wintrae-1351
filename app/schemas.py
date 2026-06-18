from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from app.models import LockerSize, LockerStatus, OrderStatus


class StoreOut(BaseModel):
    id: int
    name: str
    address: str
    phone: Optional[str] = None
    is_active: bool

    model_config = {"from_attributes": True}


class LockerOut(BaseModel):
    id: int
    store_id: int
    locker_no: str
    size: LockerSize
    status: LockerStatus

    model_config = {"from_attributes": True}


class OrderCreate(BaseModel):
    user_phone: str = Field(..., max_length=20)
    store_id: int
    locker_size: LockerSize = LockerSize.medium


class OrderOut(BaseModel):
    id: int
    order_no: str
    user_phone: str
    store_id: int
    locker_id: Optional[int] = None
    drop_code: Optional[str] = None
    pickup_code: Optional[str] = None
    status: OrderStatus
    total_fee: float
    timeout_at: Optional[datetime] = None
    pickup_reminded: bool
    created_at: datetime
    dropped_at: Optional[datetime] = None
    received_at: Optional[datetime] = None
    washing_at: Optional[datetime] = None
    done_at: Optional[datetime] = None
    returned_at: Optional[datetime] = None
    picked_up_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class FeeItemOut(BaseModel):
    id: int
    order_id: int
    item_name: str
    unit_price: float
    quantity: int
    amount: float

    model_config = {"from_attributes": True}


class FeeItemCreate(BaseModel):
    item_name: str
    unit_price: float
    quantity: int = 1


class OrderLogOut(BaseModel):
    id: int
    order_id: int
    action: str
    detail: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class PhoneUpdate(BaseModel):
    user_phone: str = Field(..., max_length=20)


class ConfirmReceivedRequest(BaseModel):
    fee_items: list[FeeItemCreate] = []


class UpdateWashingRequest(BaseModel):
    progress_note: str = ""


class MarkReturnedRequest(BaseModel):
    pickup_code: str = Field(..., min_length=4, max_length=8)


class SendPickupReminderRequest(BaseModel):
    message: str = ""


class LockerAbnormalOut(BaseModel):
    id: int
    store_id: int
    locker_no: str
    size: LockerSize
    status: LockerStatus
    is_abnormal: bool
    abnormal_note: Optional[str] = None

    model_config = {"from_attributes": True}


class DailyCompletionOut(BaseModel):
    store_id: int
    store_name: str
    dropped_count: int
    picked_up_count: int
    date: str


class StoreOrderSummaryOut(BaseModel):
    store_id: int
    store_name: str
    total_orders: int
    created_count: int
    washing_count: int
    done_count: int
    returned_count: int
    picked_up_count: int
    cancelled_count: int
    total_fee: float


class AvailableLockerQuery(BaseModel):
    store_id: int
    size: Optional[LockerSize] = None


class TimeoutHandleResult(BaseModel):
    processed_count: int
    timeout_order_ids: list[int]
