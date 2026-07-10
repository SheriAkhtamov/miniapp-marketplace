import re
from typing import List, Optional, Literal
from fastapi import Form, HTTPException
from pydantic import BaseModel, Field, ValidationError, validator
from .base import FormSchema

class OrderCreateSchema(FormSchema):
    item_ids: List[int]
    delivery_method: Literal["pickup", "delivery"]
    delivery_option_id: Optional[str] = Field(None, max_length=100)
    payment_method: Literal["cash", "card", "click", "card_transfer"]
    phone: str
    address: Optional[str] = Field(None, max_length=500)
    delivery_latitude: Optional[float] = None
    delivery_longitude: Optional[float] = None
    delivery_location_source: Optional[str] = Field(None, max_length=50)
    comment: Optional[str] = Field(None, max_length=500)
    promo_code: Optional[str] = Field(None, max_length=50)

    @validator("phone")
    def validate_phone(cls, v):
        # Remove +, parentheses, spaces, hyphens
        v = re.sub(r'[^\d]', '', v)
        
        # Автоматически добавляем 998 если введены только 9 цифр (узбекский локальный)
        if len(v) == 9:
            v = "998" + v

        # Accept international numbers: 7-15 digits (ITU-T E.164)
        if 7 <= len(v) <= 15:
            return v

        raise ValueError("Неверный формат телефона. Введите номер от 7 до 15 цифр")

    @validator("address")
    def validate_address(cls, v, values):
        method = values.get("delivery_method")
        if method == "delivery" and not v:
            raise ValueError("Адрес обязателен для доставки")
        return v

    @validator("delivery_latitude", pre=True)
    def validate_latitude(cls, v):
        if v is None or v == "":
            return None
        if not -90 <= float(v) <= 90:
            raise ValueError("Некорректная широта")
        return float(v)

    @validator("delivery_longitude", pre=True)
    def validate_longitude(cls, v):
        if v is None or v == "":
            return None
        if not -180 <= float(v) <= 180:
            raise ValueError("Некорректная долгота")
        return float(v)

    @validator("delivery_location_source")
    def validate_location_source(cls, v, values):
        source = (v or "").strip()
        lat = values.get("delivery_latitude")
        lon = values.get("delivery_longitude")
        if source and source != "browser_geolocation":
            raise ValueError("Некорректный источник геолокации")
        if source == "browser_geolocation" and (lat is None or lon is None):
            raise ValueError("Геолокация не получена")
        if not source and (lat is not None or lon is not None):
            raise ValueError("Некорректный источник геолокации")
        if (lat is None) != (lon is None):
            raise ValueError("Некорректная геолокация")
        return source or None

    @classmethod
    def as_form(
        cls,
        item_ids: List[int] = Form(...),
        delivery_method: str = Form(..., pattern="^(pickup|delivery)$"),
        delivery_option_id: Optional[str] = Form(None),
        payment_method: str = Form(..., pattern="^(cash|card|click|card_transfer)$"),
        phone: str = Form(...),
        address: Optional[str] = Form(None),
        delivery_latitude: Optional[str] = Form(None),
        delivery_longitude: Optional[str] = Form(None),
        delivery_location_source: Optional[str] = Form(None),
        comment: Optional[str] = Form(None),
        promo_code: Optional[str] = Form(None),
    ):
        try:
            return cls(
                item_ids=item_ids,
                delivery_method=delivery_method,
                delivery_option_id=delivery_option_id,
                payment_method=payment_method,
                phone=phone,
                address=address,
                delivery_latitude=delivery_latitude,
                delivery_longitude=delivery_longitude,
                delivery_location_source=delivery_location_source,
                comment=comment,
                promo_code=promo_code
            )
        except ValidationError as exc:
            errors = [f"{err['loc'][0]}: {err['msg']}" for err in exc.errors()]
            raise HTTPException(status_code=422, detail="; ".join(errors))
