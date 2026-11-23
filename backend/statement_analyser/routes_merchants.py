"""Merchant identification API. Built with a factory so it shares main.py's settings dependency (tests override it)."""
from functools import lru_cache
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from statement_analyser.config import Settings
from statement_analyser.schemas import MerchantCorrection, MerchantIdentifyRequest, MerchantMapping, MerchantResult
from statement_analyser.services.merchant_identifier import MerchantMappingStore, identify_merchants


@lru_cache
def _store(path: str) -> MerchantMappingStore:
    return MerchantMappingStore(path)


def create_router(settings_dep) -> APIRouter:
    router = APIRouter(prefix="/api/merchants", tags=["merchants"])

    def store_dep(s: Settings = Depends(settings_dep)) -> MerchantMappingStore:
        return _store(s.db_path)

    @router.post("/identify", response_model=list[MerchantResult])
    def identify(body: MerchantIdentifyRequest, store: MerchantMappingStore = Depends(store_dep)):
        """One result per description, same order. Saved corrections are applied first."""
        return identify_merchants(body.descriptions, store.list())

    @router.get("/mappings", response_model=list[MerchantMapping])
    def list_mappings(q: Optional[str] = None, store: MerchantMappingStore = Depends(store_dep)):
        return store.list(q)

    @router.post("/mappings", response_model=MerchantMapping, status_code=201)
    def save_mapping(body: MerchantCorrection, store: MerchantMappingStore = Depends(store_dep)):
        try:
            return store.save_manual_mapping(body.narration, body.merchant_name, body.category, body.alias)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.delete("/mappings/{mapping_id}", status_code=204)
    def delete_mapping(mapping_id: int, store: MerchantMappingStore = Depends(store_dep)):
        if not store.delete(mapping_id):
            raise HTTPException(404, "Mapping not found.")

    return router
