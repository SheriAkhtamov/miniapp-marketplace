import re
from typing import Optional
from fastapi import Form, UploadFile, File, HTTPException
from pydantic import BaseModel, Field, field_validator, ValidationError
from .base import FormSchema
from app.config import settings

class ProductCreateSchema(FormSchema):
    name_ru: str = Field(..., min_length=2)
    name_uz: str = Field(..., min_length=2)
    category_id: int
    price: int = Field(..., gt=0)
    discount_price: Optional[int] = Field(None, gt=0)
    stock: int = Field(..., ge=0)
    sell_type: str = Field("piece")  # piece / pack
    pack_quantity: Optional[int] = None  # кол-во единиц в упаковке
    description_ru: Optional[str] = ""
    description_uz: Optional[str] = ""
    ikpu: str = Field("00702001001000000", min_length=14, max_length=17)
    package_code: str = Field(settings.DEFAULT_PACKAGE_CODE, min_length=1)

    @field_validator('ikpu')
    @classmethod
    def ikpu_must_be_17_digits(cls, v: str) -> str:
        v = v.strip()
        if not re.fullmatch(r'\d{14,17}', v):
            raise ValueError('ИКПУ должен содержать от 14 до 17 цифр')
        return v
    
    # Image is handled separately via File(), but we can include it in the model info if needed.
    # For now, we keep it separate in the Depends because it's UploadFile
    
    @classmethod
    def as_form(
        cls,
        name_ru: str = Form(...),
        name_uz: str = Form(...),
        category_id: int = Form(...),
        price: int = Form(...),
        discount_price: Optional[str] = Form(None),
        stock: int = Form(...),
        sell_type: str = Form("piece"),
        pack_quantity: Optional[str] = Form(None),
        description_ru: str = Form(""),
        description_uz: str = Form(""),
        ikpu: str = Form("00702001001000000"),
        package_code: str = Form(settings.DEFAULT_PACKAGE_CODE),
    ):
        pack_qty_int = None
        if pack_quantity is not None and str(pack_quantity).strip() != "":
            try:
                pack_qty_int = int(pack_quantity)
            except (ValueError, TypeError):
                pack_qty_int = None
        discount_price_int = None
        if discount_price is not None and str(discount_price).strip() != "":
            try:
                parsed_discount = int(discount_price)
                if parsed_discount > 0:
                    discount_price_int = parsed_discount
            except (ValueError, TypeError):
                discount_price_int = None
        try:
            return cls(
                name_ru=name_ru,
                name_uz=name_uz,
                category_id=category_id,
                price=price,
                discount_price=discount_price_int,
                stock=stock,
                sell_type=sell_type,
                pack_quantity=pack_qty_int,
                description_ru=description_ru,
                description_uz=description_uz,
                ikpu=ikpu,
                package_code=package_code,
            )
        except ValidationError as exc:
            errors = [f"{err['loc'][0]}: {err['msg']}" for err in exc.errors()]
            raise HTTPException(status_code=422, detail="; ".join(errors))
