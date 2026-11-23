import pytest

from statement_analyser.services.merchant_identifier import (
    UNKNOWN,
    MerchantMappingStore,
    detect_platform,
    identify_merchant,
    identify_merchants,
    map_merchant_category,
    normalize_narration,
)


@pytest.mark.parametrize(
    "narration, merchant, category",
    [
        ("UPI/P2M/98372/AMAZON", "Amazon", "Shopping"),  # examples from the requirements
        ("UPI/SWIGGY/123456", "Swiggy", "Food"),
        ("POS/DMART/STORE01", "DMart", "Groceries"),
        ("UPI/ZOMATO@icici/lunch", "Zomato", "Food"),
        ("UPI/BIGBASKET GROCERIES", "BigBasket", "Groceries"),
        ("IMPS/REFUND AMAZON", "Amazon", "Shopping"),
        ("ELECTRICITY BILL MSEDCL", "MSEDCL", "Utilities"),  # a brand beats the generic "electricity bill"
        ("MOBILE RECHARGE", "Mobile Recharge", "Utilities"),
        ("UPI/PETROL PUMP", "Petrol Pump", "Transport"),
        ("INTEREST CREDIT", "Bank Interest", "Banking"),
        ("ATM CASH WITHDRAWAL BANER MONTHLY PAYMENT", "ATM Withdrawal", "Banking"),
        ("UPI/UBER INDIA/RIDE 8834", "Uber", "Transport"),
        ("NETFLIX.COM MUMBAI", "Netflix", "Entertainment"),
        ("D MART KOTHRUD", "DMart", "Groceries"),
        ("AMAZON PRIME VIDEO", "Amazon Prime", "Entertainment"),  # the longer alias wins over plain Amazon
        ("SWIGGY INSTAMART", "Swiggy Instamart", "Groceries"),
    ],
)
def test_known_merchants(narration, merchant, category):
    r = identify_merchant(narration)
    assert (r["merchant_name"], r["category"], r["status"]) == (merchant, category, "Identified")
    assert 0.70 <= r["confidence"] <= 1.0
    assert r["reason"]


@pytest.mark.parametrize(
    "narration",
    [
        "SALARY CREDIT ACME PVT LTD",  # no merchant we can name
        "NEFT/RENT PAYMENT",
        "UPI/PAYTM/9876543210",  # only a payment app and an id
        "Current account charges",  # "rent" must not match inside "current"
        "Business loan",  # "bus" must not match inside "business"
        "COCA COLA",  # "ola" must not match inside "cola"
        "UPI/P2M/98372",  # only ids
        "",
        None,
    ],
)
def test_unknown_merchant_when_not_reliable(narration):
    r = identify_merchant(narration)
    assert r["merchant_name"] == UNKNOWN == "Unknown Merchant"
    assert r["status"] == "Unknown" and r["category"] == "Other"
    assert r["confidence"] < 0.70 and r["reason"]


def test_ambiguous_narration_is_not_guessed():
    r = identify_merchant("SWIGGY AMAZON")
    assert r["merchant_name"] == UNKNOWN
    assert "Ambiguous" in r["reason"] and "Amazon" in r["reason"] and "Swiggy" in r["reason"]


def test_normalization_is_a_copy_without_noise():
    original = "UPI/P2M/98372/AMAZON REF TXN62992312 12/09/2026"
    assert normalize_narration(original) == "amazon"
    assert original == "UPI/P2M/98372/AMAZON REF TXN62992312 12/09/2026"  # the input is never altered
    assert normalize_narration(None) == ""


def test_platform_detection():
    assert detect_platform("UPI/SWIGGY@ybl/1234") == "UPI via PhonePe"
    assert detect_platform("POS/DMART/STORE01") == "POS"
    assert detect_platform("plain text") is None


def test_confidence_is_higher_with_a_known_payment_format():
    with_format = identify_merchant("UPI/OLA/1234")["confidence"]
    without = identify_merchant("OLA")["confidence"]
    assert with_format > without >= 0.70  # short alias without a payment format is trusted less, but still reliable


def test_category_lookup():
    assert map_merchant_category("swiggy") == "Food"
    assert map_merchant_category("Some Corner Shop") == "Other"


def test_batch_keeps_order():
    out = identify_merchants(["UPI/SWIGGY/1", "mystery text", None])
    assert [r["merchant_name"] for r in out] == ["Swiggy", UNKNOWN, UNKNOWN]


# ---- saved corrections ------------------------------------------------------------------------
@pytest.fixture
def store(tmp_path):
    return MerchantMappingStore(str(tmp_path / "m.db"))


def test_correction_is_saved_and_reused(store):
    narration = "UPI/GREEN LEAF STORES/55512/ref"
    assert identify_merchant(narration, store.list())["merchant_name"] == UNKNOWN
    saved = store.save_manual_mapping(narration, "Green Leaf Stores", "Groceries")
    assert saved["aliases"] == ["green leaf stores"] and saved["source"] == "user"
    again = identify_merchant("POS/GREEN LEAF STORES/TERM77", store.list())  # different format, same merchant
    assert (again["merchant_name"], again["category"], again["status"], again["confidence"]) == ("Green Leaf Stores", "Groceries", "User Corrected", 1.0)


def test_correction_beats_built_in_alias(store):
    store.save_manual_mapping("UPI/AMAZON/1", "Amazon Pantry", "Groceries")
    r = identify_merchant("UPI/P2M/98372/AMAZON", store.list())
    assert (r["merchant_name"], r["source"]) == ("Amazon Pantry", "user")


def test_alias_moves_to_the_newest_merchant(store):
    store.save_manual_mapping("UPI/CORNER CAFE/1", "Corner Cafe", "Food")
    store.save_manual_mapping("UPI/CORNER CAFE/1", "Corner Bakery", "Food")
    names = {m["merchant_name"]: m["aliases"] for m in store.list()}
    assert names == {"Corner Cafe": [], "Corner Bakery": ["corner cafe"]}


def test_get_or_create_is_idempotent_and_updates_category(store):
    a = store.get_or_create_merchant_mapping("Raju Tea", "Food")
    b = store.get_or_create_merchant_mapping("raju tea", "Other")
    assert a["id"] == b["id"] and b["category"] == "Other" and len(store.list()) == 1


def test_search_and_delete(store):
    m = store.save_manual_mapping("UPI/GREEN LEAF STORES/1", "Green Leaf Stores", "Groceries")
    store.save_manual_mapping("UPI/RAJU TEA/1", "Raju Tea", "Food")
    assert [x["merchant_name"] for x in store.list("leaf")] == ["Green Leaf Stores"]
    assert store.delete(m["id"]) and not store.delete(m["id"])
    assert identify_merchant("GREEN LEAF STORES", store.list())["merchant_name"] == UNKNOWN


@pytest.mark.parametrize(
    "args",
    [
        ("UPI/98372/55512", "Shop", "Food"),  # only ids: nothing to remember
        ("UPI/SHOP/1", "Unknown Merchant", "Food"),
        ("UPI/SHOP/1", "  ", "Food"),
        ("UPI/SHOP/1", "Shop", "Salary"),  # not a merchant category
    ],
)
def test_bad_corrections_rejected(store, args):
    with pytest.raises(ValueError):
        store.save_manual_mapping(*args)


# ---- API ---------------------------------------------------------------------------------------
def test_identify_endpoint_and_corrections(client):
    r = client.post("/api/merchants/identify", json={"descriptions": ["UPI/SWIGGY/123456", "UPI/GREEN LEAF STORES/9", None]})
    assert r.status_code == 200, r.text
    out = r.json()
    assert [x["merchant_name"] for x in out] == ["Swiggy", "Unknown Merchant", "Unknown Merchant"]
    assert out[0]["confidence"] >= 0.9 and out[0]["reason"] and out[0]["platform"] == "UPI"

    c = client.post("/api/merchants/mappings", json={"narration": "UPI/GREEN LEAF STORES/9", "merchant_name": "Green Leaf", "category": "Groceries"})
    assert c.status_code == 201, c.text
    assert c.json()["aliases"] == ["green leaf stores"]
    again = client.post("/api/merchants/identify", json={"descriptions": ["UPI/GREEN LEAF STORES/777"]}).json()[0]
    assert (again["merchant_name"], again["status"]) == ("Green Leaf", "User Corrected")

    assert [m["merchant_name"] for m in client.get("/api/merchants/mappings", params={"q": "leaf"}).json()] == ["Green Leaf"]
    assert client.get("/api/merchants/mappings", params={"q": "zzz"}).json() == []
    assert client.delete(f"/api/merchants/mappings/{c.json()['id']}").status_code == 204
    assert client.delete(f"/api/merchants/mappings/{c.json()['id']}").status_code == 404


def test_api_validation(client):
    bad = {"narration": "UPI/SHOP/1", "merchant_name": "Shop", "category": "Salary"}
    assert client.post("/api/merchants/mappings", json=bad).status_code == 422
    only_ids = {"narration": "UPI/98372", "merchant_name": "Shop", "category": "Food"}
    assert client.post("/api/merchants/mappings", json=only_ids).status_code == 422
    assert client.post("/api/merchants/identify", json={"descriptions": ["x" * 501]}).status_code == 422


def test_identify_does_not_change_saved_statements(client):
    body = {
        "file_name": "s.pdf",
        "header": {},
        "transactions": [{"date": "2026-09-02", "description": "UPI/SWIGGY/123456", "reference": "TXN1", "withdrawal": "100.00"}],
    }
    sid = client.post("/api/statements", json=body).json()["id"]
    before = client.get(f"/api/statements/{sid}").json()
    client.post("/api/merchants/identify", json={"descriptions": ["UPI/SWIGGY/123456"]})
    client.post("/api/merchants/mappings", json={"narration": "UPI/SWIGGY/123456", "merchant_name": "Swiggy Eats", "category": "Food"})
    assert client.get(f"/api/statements/{sid}").json() == before
