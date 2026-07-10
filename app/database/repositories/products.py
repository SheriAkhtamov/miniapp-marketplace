import re
from typing import List, Optional
from sqlalchemy import func, literal_column, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.models import Category, Product
from .base import BaseRepository


_SEARCH_TOKEN_RE = re.compile(r"[0-9A-Za-zА-Яа-яЁёЎўҚқҒғҲҳ]+", re.UNICODE)


class ProductRepository(BaseRepository[Product]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, Product)

    async def get_active(self, limit: int = 50) -> List[Product]:
        stmt = (
            select(Product)
            .join(Category, Category.id == Product.category_id)
            .where(Product.is_active == True, Category.is_active == True)
            .limit(limit)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def get_by_category(self, category_id: int) -> List[Product]:
         stmt = (
             select(Product)
             .join(Category, Category.id == Product.category_id)
             .where(
                 Product.is_active == True,
                 Product.category_id == category_id,
                 Category.is_active == True,
             )
         )
         return (await self.session.execute(stmt)).scalars().all()

    async def get_visible_by_id(self, product_id: int) -> Optional[Product]:
        stmt = (
            select(Product)
            .join(Category, Category.id == Product.category_id)
            .where(
                Product.id == product_id,
                Product.is_active == True,
                Category.is_active == True,
            )
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def search(self, query: str) -> List[Product]:
        products, _ = await self.get_filtered(query=query, limit=50, offset=0)
        return products

    @staticmethod
    def _tokenize_search_query(query: str) -> list[str]:
        seen: set[str] = set()
        tokens: list[str] = []
        for token in _SEARCH_TOKEN_RE.findall((query or "").lower()):
            if len(token) < 2 or token in seen:
                continue
            seen.add(token)
            tokens.append(token)
        return tokens

    @classmethod
    def _build_tsquery(cls, query: str) -> Optional[str]:
        tokens = cls._tokenize_search_query(query)
        if not tokens:
            return None
        return " & ".join(f"{token}:*" for token in tokens)

    @classmethod
    def _build_search_expressions(cls, query: str):
        normalized_query = (query or "").strip().lower()
        ts_query = cls._build_tsquery(normalized_query)
        if not ts_query:
            return None

        ru_config = literal_column("'russian'")
        uz_config = literal_column("'simple'")
        ru_text = func.concat_ws(
            " ",
            func.coalesce(Product.name_ru, ""),
            func.coalesce(Product.description_ru, ""),
        )
        uz_text = func.concat_ws(
            " ",
            func.coalesce(Product.name_uz, ""),
            func.coalesce(Product.description_uz, ""),
        )

        ru_vector = func.to_tsvector(ru_config, ru_text)
        uz_vector = func.to_tsvector(uz_config, uz_text)
        ru_query = func.to_tsquery(ru_config, ts_query)
        uz_query = func.to_tsquery(uz_config, ts_query)

        rank_expr = func.greatest(
            func.ts_rank_cd(ru_vector, ru_query),
            func.ts_rank_cd(uz_vector, uz_query),
        )
        similarity_expr = func.greatest(
            func.similarity(func.lower(func.coalesce(Product.name_ru, "")), normalized_query),
            func.similarity(func.lower(func.coalesce(Product.name_uz, "")), normalized_query),
        )

        condition = or_(
            ru_vector.op("@@")(ru_query),
            uz_vector.op("@@")(uz_query),
            func.lower(func.coalesce(Product.name_ru, "")).op("%")(normalized_query),
            func.lower(func.coalesce(Product.name_uz, "")).op("%")(normalized_query),
        )

        return condition, rank_expr, similarity_expr

    async def get_filtered(
        self,
        *,
        query: str = "",
        category_id: Optional[int] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Product], int]:
        stmt = (
            select(Product)
            .join(Category, Category.id == Product.category_id)
            .where(Product.is_active == True, Category.is_active == True)
        )

        if category_id is not None:
            stmt = stmt.where(Product.category_id == category_id)

        order_by = [Product.id.desc()]
        if query.strip():
            expressions = self._build_search_expressions(query)
            if expressions is None:
                return [], 0
            condition, rank_expr, similarity_expr = expressions
            stmt = stmt.where(condition)
            order_by = [rank_expr.desc(), similarity_expr.desc(), Product.id.desc()]

        total_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(total_stmt)).scalar() or 0

        stmt = stmt.order_by(*order_by).limit(limit).offset(offset)
        products = (await self.session.execute(stmt)).scalars().all()
        return products, total

    async def get_with_lock(self, product_id: int) -> Optional[Product]:
        stmt = select(Product).where(Product.id == product_id).with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()
