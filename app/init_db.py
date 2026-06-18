import random
import string
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.database import engine, SessionLocal, Base
from app.models import Store, Locker, LockerSize, LockerStatus


def generate_order_no():
    ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    rand = "".join(random.choices(string.digits, k=4))
    return f"ORD{ts}{rand}"


def generate_code(length=6):
    return "".join(random.choices(string.digits, k=length))


def init_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.query(Store).first():
            return
        stores_data = [
            {"name": "阳光洗衣柜·朝阳店", "address": "朝阳区建国路88号", "phone": "010-88881001"},
            {"name": "阳光洗衣柜·海淀店", "address": "海淀区中关村大街66号", "phone": "010-88881002"},
            {"name": "阳光洗衣柜·西城店", "address": "西城区金融街22号", "phone": "010-88881003"},
        ]
        for sd in stores_data:
            store = Store(**sd)
            db.add(store)
            db.flush()
            for i in range(1, 13):
                size = LockerSize.small if i <= 4 else (LockerSize.medium if i <= 8 else LockerSize.large)
                locker = Locker(
                    store_id=store.id,
                    locker_no=f"{size.value[0].upper()}{i:02d}",
                    size=size,
                    status=LockerStatus.available,
                )
                db.add(locker)
        db.commit()
        print("Database initialized with seed data.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    init_db()
