from sqlalchemy import BigInteger, String, ForeignKey, Boolean, Text, Integer, DateTime, func, UniqueConstraint, Numeric, JSON, Table, Column, Index, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import List, Optional
from decimal import Decimal
from datetime import datetime
from app.database.core import Base

promo_banner_products = Table(
    "promo_banner_products",
    Base.metadata,
    Column("banner_id", ForeignKey("promo_banners.id", ondelete="CASCADE"), primary_key=True),
    Column("product_id", ForeignKey("products.id", ondelete="CASCADE"), primary_key=True),
)

# --- Пользователи и Сотрудники ---
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=True)
    username: Mapped[str] = mapped_column(String, nullable=True)
    phone: Mapped[str] = mapped_column(String, nullable=True)
    language: Mapped[str] = mapped_column(String, default="ru") # ru / uz
    
    # Роли: user, manager, superadmin
    role: Mapped[str] = mapped_column(String, default="user")

    # Долг пользователя (в сумах)
    debt: Mapped[int] = mapped_column(Integer, default=0)
    
    # Поля для сотрудников (менеджеров)
    login: Mapped[str] = mapped_column(String, nullable=True, unique=True)
    password_hash: Mapped[str] = mapped_column(String, nullable=True)
    
    # Разрешения менеджера (JSON): {"products": true, "orders": true, ...}
    permissions: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    # Связи
    orders: Mapped[List["Order"]] = relationship(back_populates="user")
    addresses: Mapped[List["UserAddress"]] = relationship(back_populates="user")
    favorites: Mapped[List["Favorite"]] = relationship(back_populates="user")

class UserAddress(Base):
    __tablename__ = "user_addresses"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    address_text: Mapped[str] = mapped_column(Text)
    
    user: Mapped["User"] = relationship(back_populates="addresses")

# --- Товары ---
class Category(Base):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    name_ru: Mapped[str] = mapped_column(String, unique=True)
    name_uz: Mapped[str] = mapped_column(String)
    image_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    products: Mapped[List["Product"]] = relationship(back_populates="category")

    __table_args__ = (
        Index("uq_categories_name_ru_normalized", func.lower(func.trim(name_ru)), unique=True),
        Index("uq_categories_name_uz_normalized", func.lower(func.trim(name_uz)), unique=True),
    )


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)

class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), index=True)
    
    name_ru: Mapped[str] = mapped_column(String, index=True)
    name_uz: Mapped[str] = mapped_column(String, index=True)
    description_ru: Mapped[str] = mapped_column(Text, nullable=True)
    description_uz: Mapped[str] = mapped_column(Text, nullable=True)
    
    price: Mapped[int] = mapped_column(BigInteger) # Храним в сумах
    discount_price: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    stock: Mapped[int] = mapped_column(Integer, default=0)
    
    # Формат продажи: piece (поштучно) или pack (упаковками)
    sell_type: Mapped[str] = mapped_column(String, default="piece")  # piece / pack
    pack_quantity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # кол-во единиц в упаковке
    
    image_path: Mapped[str] = mapped_column(String)

    # Новые поля для фискализации
    ikpu: Mapped[str] = mapped_column(String, default="00702001001000000", nullable=True)
    package_code: Mapped[str] = mapped_column(String, default="000000", nullable=True)
    
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_popular: Mapped[bool] = mapped_column(Boolean, default=False)
    popular_sort_order: Mapped[int] = mapped_column(Integer, default=0)

    category: Mapped["Category"] = relationship(back_populates="products")
    cart_items: Mapped[List["CartItem"]] = relationship(back_populates="product")
    favorites: Mapped[List["Favorite"]] = relationship(back_populates="product")
    images: Mapped[List["ProductImage"]] = relationship(back_populates="product", cascade="all, delete-orphan")
    banners: Mapped[List["PromoBanner"]] = relationship(
        secondary=promo_banner_products,
        back_populates="products",
    )

    @property
    def has_discount(self) -> bool:
        return bool(
            self.discount_price
            and self.price
            and self.discount_price > 0
            and self.discount_price < self.price
        )

    @property
    def effective_price(self) -> int:
        return int(self.discount_price) if self.has_discount else int(self.price or 0)

    @property
    def discount_percent(self) -> int:
        if not self.has_discount:
            return 0
        return max(1, round((self.price - self.discount_price) * 100 / self.price))

# --- Корзина и Избранное ---
class CartItem(Base):
    __tablename__ = "cart_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    
    product: Mapped["Product"] = relationship(back_populates="cart_items")

    __table_args__ = (
        UniqueConstraint("user_id", "product_id", name="_user_product_cart_uc"),
    )

class Favorite(Base):
    __tablename__ = "favorites"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))

    user: Mapped["User"] = relationship(back_populates="favorites")
    product: Mapped["Product"] = relationship(back_populates="favorites")
    
    __table_args__ = (
        UniqueConstraint('user_id', 'product_id', name='_user_product_favorite_uc'),
    )

# --- Per-user promo usage tracking ---
class UserPromoUsage(Base):
    __tablename__ = "user_promo_usages"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    promo_id: Mapped[int] = mapped_column(ForeignKey("promo_codes.id"), index=True)
    used_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint('user_id', 'promo_id', name='_user_promo_usage_uc'),
    )

# --- Rate Limiting ---
class OrderRateLimit(Base):
    __tablename__ = "order_rate_limits"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)

# --- Заказы ---
class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    customer_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    status: Mapped[str] = mapped_column(String, default="new", index=True) # new, paid, delivery, done, cancelled
    admin_unread: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    order_type: Mapped[str] = mapped_column(String, default="product") # product, debt_repayment
    payment_method: Mapped[str] = mapped_column(String) # cash, card, click, card_transfer
    payment_receipt_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    delivery_method: Mapped[str] = mapped_column(String) # pickup, delivery
    delivery_option_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    delivery_option_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    delivery_price: Mapped[int] = mapped_column(Integer, default=0)

    delivery_address: Mapped[str] = mapped_column(Text, nullable=True)
    delivery_latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    delivery_longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    total_amount: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str] = mapped_column(Text, nullable=True)
    contact_phone: Mapped[str] = mapped_column(String, index=True)
    
    promo_code_id: Mapped[Optional[int]] = mapped_column(ForeignKey("promo_codes.id"), nullable=True)
    discount_amount: Mapped[int] = mapped_column(Integer, default=0)
    
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, index=True)

    user: Mapped[Optional["User"]] = relationship(back_populates="orders")
    items: Mapped[List["OrderItem"]] = relationship(back_populates="order")
    promo_code: Mapped[Optional["PromoCode"]] = relationship()
    # Связь с транзакциями Payme (может быть несколько попыток оплаты)
    payme_transactions: Mapped[List["PaymeTransaction"]] = relationship(back_populates="order")

class OrderItem(Base):
    __tablename__ = "order_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=True)
    product_name: Mapped[str] = mapped_column(String)
    price_at_purchase: Mapped[int] = mapped_column(Integer)
    quantity: Mapped[int] = mapped_column(Integer)
    stock_before_order: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    
    order: Mapped["Order"] = relationship(back_populates="items")
    product: Mapped["Product"] = relationship()

# --- PAYME ТРАНЗАКЦИИ ---
class PaymeTransaction(Base):
    __tablename__ = "payme_transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Payme присылает свой ID транзакции (длинная строка), он должен быть уникальным
    payme_id: Mapped[str] = mapped_column(String, unique=True, index=True) 
    time: Mapped[int] = mapped_column(BigInteger) # Время создания в Payme (timestamp ms)
    amount: Mapped[int] = mapped_column(BigInteger) # Сумма в тийинах
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    
    # Состояние транзакции (по документации Payme):
    # 1 - Создана (ожидает подтверждения)
    # 2 - Подтверждена (деньги списаны)
    # -1 - Отменена
    # -2 - Отменена после завершения
    state: Mapped[int] = mapped_column(Integer, default=1)
    
    reason: Mapped[int] = mapped_column(Integer, nullable=True) # Причина отмены
    
    create_time: Mapped[datetime] = mapped_column(default=datetime.utcnow) # Наше время создания
    perform_time: Mapped[datetime] = mapped_column(DateTime, nullable=True) # Время подтверждения
    cancel_time: Mapped[datetime] = mapped_column(DateTime, nullable=True) # Время отмены

    order: Mapped["Order"] = relationship(back_populates="payme_transactions")

# --- CLICK ТРАНЗАКЦИИ ---
class ClickTransaction(Base):
    __tablename__ = "click_transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    click_trans_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True) # ID транзакции в Click
    service_id: Mapped[int] = mapped_column(Integer)
    click_paydoc_id: Mapped[int] = mapped_column(BigInteger)
    merchant_trans_id: Mapped[str] = mapped_column(String, index=True) # Наш ID заказа
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2)) # Сумма
    action: Mapped[int] = mapped_column(Integer) # 0=Prepare, 1=Complete
    error: Mapped[int] = mapped_column(Integer)
    error_note: Mapped[str] = mapped_column(String, nullable=True)
    sign_time: Mapped[str] = mapped_column(String)
    sign_string: Mapped[str] = mapped_column(String)
    
    status: Mapped[str] = mapped_column(String, default="input") # input, canceled, confirmed
    
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

# --- ДОПОЛНИТЕЛЬНЫЕ ФОТО ТОВАРОВ ---
class ProductImage(Base):
    __tablename__ = "product_images"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    image_path: Mapped[str] = mapped_column(String)
    media_type: Mapped[str] = mapped_column(String, default="image")  # image / video
    poster_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    product: Mapped["Product"] = relationship(back_populates="images")

# --- ПРОМОКОДЫ ---
class PromoCode(Base):
    __tablename__ = "promo_codes"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String, unique=True, index=True)
    discount_type: Mapped[str] = mapped_column(String, default="percent")  # percent / fixed
    discount_value: Mapped[int] = mapped_column(Integer)  # % или сумма
    min_order_amount: Mapped[int] = mapped_column(Integer, default=0)
    max_discount: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # макс скидка для percent
    usage_limit: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # сколько раз можно использовать
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

# --- ПРОМО-БАННЕРЫ ---
class PromoBanner(Base):
    __tablename__ = "promo_banners"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    subtitle: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    badge_text: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    image_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    link: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    products: Mapped[List["Product"]] = relationship(
        secondary=promo_banner_products,
        back_populates="banners",
    )

# --- АУДИТ ЛОГ ---
class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String, index=True)  # create_product, update_order, etc.
    entity_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # product, order, user
    entity_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON-описание изменений
    ip_address: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, index=True)

    user: Mapped[Optional["User"]] = relationship()

# --- УВЕДОМЛЕНИЯ О НАЛИЧИИ ---
class StockNotification(Base):
    __tablename__ = "stock_notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    notified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    user: Mapped["User"] = relationship()
    product: Mapped["Product"] = relationship()

    __table_args__ = (
        UniqueConstraint('user_id', 'product_id', name='_user_product_stock_notify_uc'),
    )

# --- ПОДДЕРЖКА (ЧАТ) ---
class SupportChat(Base):
    __tablename__ = "support_chats"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)
    last_message_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    unread_admin: Mapped[int] = mapped_column(Integer, default=0)
    unread_user: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    user: Mapped["User"] = relationship()
    messages: Mapped[List["SupportMessage"]] = relationship(back_populates="chat", order_by="SupportMessage.created_at")

class SupportMessage(Base):
    __tablename__ = "support_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("support_chats.id"), index=True)
    sender_type: Mapped[str] = mapped_column(String)  # "user" or "admin"
    sender_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    image_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, index=True)

    chat: Mapped["SupportChat"] = relationship(back_populates="messages")
    sender: Mapped[Optional["User"]] = relationship(foreign_keys=[sender_id])
