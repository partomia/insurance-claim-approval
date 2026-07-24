from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

import schemas
from database import get_db
from dependencies import get_current_customer
from models.customer import Customer
from services.dashboard_service import DashboardService

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])
dashboard_service = DashboardService()


@router.get("/stats", response_model=schemas.DashboardStatsResponse)
def get_dashboard_stats(
    customer: Customer = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    return dashboard_service.get_stats(db, customer.id)
