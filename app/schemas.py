from datetime import date
from typing import Literal

from .sectors import Sector
from pydantic import BaseModel, ConfigDict, Field, field_validator


class BusinessCreate(BaseModel):
    code: str = Field(min_length=3, max_length=20, examples=["SME-001"])
    sector: Sector
    start_date: date | None = None


class BusinessOut(BusinessCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int


class RecordCreate(BaseModel):
    month: date = Field(description="Any date in the month; stored as the 1st")
    revenue: float = Field(ge=0)
    cogs: float = Field(ge=0)
    operating_expenses: float = Field(ge=0)
    cash_inflows: float = Field(ge=0)
    cash_outflows: float = Field(ge=0)
    mobile_money_receipts: float = Field(ge=0, default=0)
    closing_stock: float = Field(ge=0, default=0)
    outstanding_debt: float = Field(ge=0, default=0)
    transaction_count: int = Field(ge=0, default=0)

    @field_validator("month")
    @classmethod
    def first_of_month(cls, v: date) -> date:
        v = v.replace(day=1)
        if v > date.today().replace(day=1):
            raise ValueError("can't be in the future")
        return v


class RecordOut(RecordCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    net_operating_result: float
