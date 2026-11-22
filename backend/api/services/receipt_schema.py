"""Validation contracts for local extraction and evidence-only Gemini suggestions."""
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictInt

MAX_ITEMS = 200
Money = Annotated[Decimal, Field(max_digits=12, decimal_places=2, allow_inf_nan=False)]


class StrictReceiptModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExtractedItem(StrictReceiptModel):
    original_description: str = Field(min_length=1, max_length=255)
    normalized_name: str = Field(max_length=255)
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=6)
    unit: Literal["", "item", "kg", "l"] = ""
    unit_price: Decimal | None = Field(default=None, max_digits=14, decimal_places=4)
    line_total: Money
    discount: Money | None = None
    category: str = Field(default="", max_length=120)
    confidence: Decimal = Field(ge=0, le=1, max_digits=3, decimal_places=2)


class ReceiptTotalsCheck(StrictReceiptModel):
    status: Literal["matches", "mismatch", "insufficient_data"]
    item_total: Money | None = None
    difference: Money | None = None


class ExtractedReceipt(StrictReceiptModel):
    merchant: str | None = Field(default=None, max_length=255)
    purchased_at: AwareDatetime | None = None
    purchase_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    currency: Literal["EUR", "BGN"] | None = None
    reference: str = Field(default="", max_length=128)
    subtotal: Money | None = None
    discounts: Money | None = None
    tax_total: Money | None = None
    total: Money | None = None
    items: list[ExtractedItem] = Field(max_length=MAX_ITEMS)
    warnings: list[str]
    totals_check: ReceiptTotalsCheck


class ItemEvidence(StrictReceiptModel):
    description_line: StrictInt
    amount_line: StrictInt


class ReceiptEvidence(StrictReceiptModel):
    merchant_line: StrictInt | None
    items: list[ItemEvidence] = Field(max_length=MAX_ITEMS)
