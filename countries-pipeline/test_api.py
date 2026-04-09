"""
Torch.AI — Testing & QA Engineer Exercise
REST Countries API Test Suite

Covers:
- Functional correctness (status codes, structure, required fields)
- Data validation (types, ranges, referential integrity)
- Negative / edge cases (bad codes, invalid endpoints)
- Performance (P95 latency under 2s)
- HTML report output via pytest-html

Usage:
    pytest test_api.py -v --html=report.html --self-contained-html
    pytest test_api.py -v -k "functional"        # only functional tests
    pytest test_api.py -v -k "performance"       # only perf tests
"""

import statistics
import time
from typing import Any

import pytest
import requests

# ─── CONFIG ──────────────────────────────────────────────────────────────────

BASE_URL = "https://restcountries.com/v3.1"
FIELDS_PARAM = "fields=name,cca2,cca3,region,subregion"
TIMEOUT = 15  # seconds per request
PERF_SAMPLES = 10  # number of requests for P95 measurement
P95_THRESHOLD_S = 2.0  # SLA: P95 must be under 2 seconds


# ─── FIXTURES ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def all_countries() -> list[dict]:
    """Fetch all countries once and reuse across tests."""
    url = f"{BASE_URL}/all?{FIELDS_PARAM}"
    resp = requests.get(url, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


@pytest.fixture(scope="session")
def us_country() -> dict:
    """Fetch United States as a known-good single-country reference."""
    resp = requests.get(f"{BASE_URL}/alpha/US?{FIELDS_PARAM}", timeout=TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    return data[0] if isinstance(data, list) else data


# ─── FUNCTIONAL TESTS ────────────────────────────────────────────────────────

class TestFunctional:
    """Core API functionality — status codes, response shape, required fields."""

    def test_all_endpoint_returns_200(self):
        resp = requests.get(f"{BASE_URL}/all?{FIELDS_PARAM}", timeout=TIMEOUT)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"

    def test_all_endpoint_returns_json(self):
        resp = requests.get(f"{BASE_URL}/all?{FIELDS_PARAM}", timeout=TIMEOUT)
        assert resp.headers["content-type"].startswith("application/json"), \
            f"Unexpected content-type: {resp.headers['content-type']}"

    def test_all_endpoint_returns_list(self, all_countries):
        assert isinstance(all_countries, list), "Expected list at top level"

    def test_country_count_reasonable(self, all_countries):
        """UN has 195 members; API covers ~250 territories. Allow 190–260."""
        count = len(all_countries)
        assert 190 <= count <= 260, f"Unexpected country count: {count}"

    def test_each_country_has_required_fields(self, all_countries):
        required = {"name", "cca2", "cca3", "region"}
        missing_fields = []
        for country in all_countries:
            missing = required - set(country.keys())
            if missing:
                name = country.get("name", {}).get("common", "unknown")
                missing_fields.append(f"{name}: missing {missing}")
        assert not missing_fields, \
            f"{len(missing_fields)} countries missing required fields:\n" + "\n".join(missing_fields[:10])

    def test_name_object_has_common_and_official(self, all_countries):
        bad = []
        for c in all_countries:
            name = c.get("name", {})
            if "common" not in name or "official" not in name:
                bad.append(c.get("cca2", "?"))
        assert not bad, f"Countries with incomplete name object: {bad[:10]}"

    def test_alpha2_code_lookup(self, us_country):
        assert us_country["cca2"] == "US"
        assert us_country["name"]["common"] == "United States"

    def test_alpha3_code_lookup(self):
        resp = requests.get(f"{BASE_URL}/alpha/DEU?{FIELDS_PARAM}", timeout=TIMEOUT)
        assert resp.status_code == 200
        data = resp.json()
        country = data[0] if isinstance(data, list) else data
        assert country["cca3"] == "DEU"
        assert country["name"]["common"] == "Germany"

    def test_region_filter_endpoint(self):
        resp = requests.get(f"{BASE_URL}/region/europe?fields=name,cca2,region", timeout=TIMEOUT)
        assert resp.status_code == 200
        countries = resp.json()
        assert isinstance(countries, list)
        assert len(countries) > 0
        for c in countries:
            assert c["region"] == "Europe", f"{c['cca2']} has region '{c['region']}', expected 'Europe'"

    def test_fields_param_filters_response_keys(self):
        resp = requests.get(f"{BASE_URL}/alpha/JP?fields=name,cca2", timeout=TIMEOUT)
        assert resp.status_code == 200
        data = resp.json()
        country = data[0] if isinstance(data, list) else data
        assert set(country.keys()) == {"name", "cca2"}, \
            f"Unexpected keys returned: {set(country.keys())}"

    def test_health_via_known_country(self):
        """Smoke test: can we retrieve at least one country successfully."""
        resp = requests.get(f"{BASE_URL}/alpha/CA?fields=name,cca2", timeout=TIMEOUT)
        assert resp.status_code == 200
        data = resp.json()
        country = data[0] if isinstance(data, list) else data
        assert country["cca2"] == "CA"


# ─── DATA VALIDATION TESTS ───────────────────────────────────────────────────

class TestDataValidation:
    """Data quality — types, value ranges, referential integrity."""

    def test_cca2_codes_are_two_uppercase_letters(self, all_countries):
        bad = [
            c["cca2"] for c in all_countries
            if not (isinstance(c.get("cca2"), str) and len(c["cca2"]) == 2 and c["cca2"].isupper())
        ]
        assert not bad, f"Invalid CCA2 codes: {bad[:10]}"

    def test_cca3_codes_are_three_uppercase_letters(self, all_countries):
        bad = [
            c["cca3"] for c in all_countries
            if not (isinstance(c.get("cca3"), str) and len(c["cca3"]) == 3 and c["cca3"].isupper())
        ]
        assert not bad, f"Invalid CCA3 codes: {bad[:10]}"

    def test_cca2_codes_unique(self, all_countries):
        codes = [c["cca2"] for c in all_countries if "cca2" in c]
        duplicates = [c for c in set(codes) if codes.count(c) > 1]
        assert not duplicates, f"Duplicate CCA2 codes: {duplicates}"

    def test_cca3_codes_unique(self, all_countries):
        codes = [c["cca3"] for c in all_countries if "cca3" in c]
        duplicates = [c for c in set(codes) if codes.count(c) > 1]
        assert not duplicates, f"Duplicate CCA3 codes: {duplicates}"

    def test_region_values_are_known(self, all_countries):
        known_regions = {"Africa", "Americas", "Asia", "Europe", "Oceania", "Antarctic", ""}
        bad = []
        for c in all_countries:
            region = c.get("region", "")
            if region not in known_regions:
                bad.append(f"{c['cca2']}: '{region}'")
        assert not bad, f"Unknown region values: {bad[:10]}"

    def test_us_population_reasonable(self):
        resp = requests.get(f"{BASE_URL}/alpha/US?fields=population", timeout=TIMEOUT)
        data = resp.json()
        country = data[0] if isinstance(data, list) else data
        pop = country.get("population", 0)
        assert 200_000_000 < pop < 400_000_000, f"US population out of range: {pop:,}"

    def test_china_population_largest(self):
        """China or India should be top 2 by population."""
        resp = requests.get(
            f"{BASE_URL}/all?fields=cca2,population",
            timeout=TIMEOUT,
        )
        countries = resp.json()
        sorted_by_pop = sorted(countries, key=lambda x: x.get("population", 0), reverse=True)
        top2_codes = {c["cca2"] for c in sorted_by_pop[:2]}
        assert "CN" in top2_codes or "IN" in top2_codes, \
            f"Expected CN or IN in top 2 by population, got: {top2_codes}"

    def test_known_subregions_present(self, all_countries):
        subregions = {c.get("subregion") for c in all_countries if c.get("subregion")}
        expected = {"Northern Europe", "Southern Asia", "Western Africa"}
        missing = expected - subregions
        assert not missing, f"Expected subregions not found: {missing}"

    def test_name_common_is_non_empty_string(self, all_countries):
        bad = [
            c.get("cca2") for c in all_countries
            if not isinstance(c.get("name", {}).get("common"), str)
            or not c["name"]["common"].strip()
        ]
        assert not bad, f"Countries with empty/invalid common name: {bad[:10]}"


# ─── NEGATIVE / EDGE CASE TESTS ──────────────────────────────────────────────

class TestNegativeCases:
    """Error handling — invalid inputs, missing resources, bad parameters."""

    def test_invalid_alpha_code_returns_error(self):
        resp = requests.get(f"{BASE_URL}/alpha/ZZZZ", timeout=TIMEOUT)
        assert resp.status_code in (400, 404), \
            f"Expected 400 or 404 for invalid code, got {resp.status_code}"

    def test_nonexistent_region_returns_404(self):
        resp = requests.get(f"{BASE_URL}/region/neverland", timeout=TIMEOUT)
        assert resp.status_code == 404, f"Expected 404 for invalid region, got {resp.status_code}"

    def test_empty_alpha_code_not_200(self):
        """Blank code should not return a successful match."""
        resp = requests.get(f"{BASE_URL}/alpha/   ", timeout=TIMEOUT)
        assert resp.status_code != 200, f"Expected non-200 for blank alpha code, got {resp.status_code}"

    def test_name_search_no_match_returns_404(self):
        resp = requests.get(f"{BASE_URL}/name/thiscountrydoesnotexist12345", timeout=TIMEOUT)
        assert resp.status_code == 404, f"Expected 404 for no-match name search, got {resp.status_code}"

    def test_sql_injection_attempt_safe(self):
        """API should not error on special characters in query params."""
        resp = requests.get(f"{BASE_URL}/name/'; DROP TABLE countries; --", timeout=TIMEOUT)
        # Should be 404, not 500
        assert resp.status_code in (400, 404), \
            f"Expected 400/404 for injected input, got {resp.status_code}"

    def test_very_long_alpha_code_safe(self):
        long_code = "A" * 200
        resp = requests.get(f"{BASE_URL}/alpha/{long_code}", timeout=TIMEOUT)
        assert resp.status_code in (400, 404), \
            f"Expected 400/404 for long code, got {resp.status_code}"

    def test_invalid_field_name_gracefully_handled(self):
        """Requesting an invalid field should not cause 500."""
        resp = requests.get(
            f"{BASE_URL}/alpha/US?fields=name,nonexistentfield",
            timeout=TIMEOUT,
        )
        # Should return 200 with the valid fields and ignore invalid ones
        assert resp.status_code != 500, f"Server error on invalid field name: {resp.status_code}"

    def test_root_endpoint_is_not_404(self):
        """The root domain should respond (even if redirect/404, not a timeout)."""
        resp = requests.get("https://restcountries.com", timeout=TIMEOUT, allow_redirects=True)
        assert resp.status_code < 500, f"Server error on root: {resp.status_code}"


# ─── PERFORMANCE TESTS ───────────────────────────────────────────────────────

class TestPerformance:
    """Latency SLA — P95 must be under 2 seconds."""

    def _measure_latency(self, url: str, n: int = PERF_SAMPLES) -> list[float]:
        """Collect n latency samples for a URL."""
        latencies = []
        for _ in range(n):
            t0 = time.perf_counter()
            resp = requests.get(url, timeout=TIMEOUT)
            elapsed = time.perf_counter() - t0
            assert resp.status_code == 200, f"Non-200 during perf test: {resp.status_code}"
            latencies.append(elapsed)
        return latencies

    def test_all_countries_p95_under_threshold(self):
        """GET /all P95 latency must be under 2 seconds."""
        url = f"{BASE_URL}/all?{FIELDS_PARAM}"
        latencies = self._measure_latency(url, n=PERF_SAMPLES)
        p95 = statistics.quantiles(latencies, n=100)[94]  # 95th percentile
        mean = statistics.mean(latencies)
        print(f"\n  /all latency — mean: {mean:.3f}s, P95: {p95:.3f}s (threshold: {P95_THRESHOLD_S}s)")
        assert p95 <= P95_THRESHOLD_S, \
            f"P95 latency {p95:.3f}s exceeds threshold {P95_THRESHOLD_S}s"

    def test_single_country_p95_under_threshold(self):
        """GET /alpha/US P95 latency must be under 2 seconds."""
        url = f"{BASE_URL}/alpha/US?fields=name,cca2,region"
        latencies = self._measure_latency(url, n=PERF_SAMPLES)
        p95 = statistics.quantiles(latencies, n=100)[94]
        mean = statistics.mean(latencies)
        print(f"\n  /alpha/US latency — mean: {mean:.3f}s, P95: {p95:.3f}s (threshold: {P95_THRESHOLD_S}s)")
        assert p95 <= P95_THRESHOLD_S, \
            f"P95 latency {p95:.3f}s exceeds threshold {P95_THRESHOLD_S}s"

    def test_region_filter_p95_under_threshold(self):
        """GET /region/europe P95 latency must be under 2 seconds."""
        url = f"{BASE_URL}/region/europe?fields=name,cca2,region"
        latencies = self._measure_latency(url, n=PERF_SAMPLES)
        p95 = statistics.quantiles(latencies, n=100)[94]
        mean = statistics.mean(latencies)
        print(f"\n  /region/europe latency — mean: {mean:.3f}s, P95: {p95:.3f}s (threshold: {P95_THRESHOLD_S}s)")
        assert p95 <= P95_THRESHOLD_S, \
            f"P95 latency {p95:.3f}s exceeds threshold {P95_THRESHOLD_S}s"

    def test_response_size_all_countries_reasonable(self):
        """Full /all response should be under 5MB (sanity check on API stability)."""
        resp = requests.get(f"{BASE_URL}/all?{FIELDS_PARAM}", timeout=TIMEOUT)
        size_mb = len(resp.content) / (1024 * 1024)
        print(f"\n  /all response size: {size_mb:.2f} MB")
        assert size_mb < 5.0, f"Response size {size_mb:.2f}MB exceeds 5MB limit"


# ─── INTEGRATION: PIPELINE → DB ──────────────────────────────────────────────

class TestPipelineIntegration:
    """End-to-end: run the pipeline and verify DB state."""

    def test_pipeline_dry_run_completes(self):
        """pipeline.py --dry-run should not raise and should return stats."""
        import sys
        import os
        sys.path.insert(0, os.path.dirname(__file__))
        from pipeline import run_pipeline

        stats = run_pipeline(dry_run=True)
        assert stats["fetched"] > 0, "Dry run fetched 0 records"

    def test_pipeline_single_country_inserts(self, tmp_path):
        """pipeline.py --country US should insert exactly 1 country row."""
        import sys
        import os
        sys.path.insert(0, os.path.dirname(__file__))
        from pipeline import run_pipeline, get_db, init_db, DB_PATH
        import pipeline as pl

        # Override DB path to a temp file
        original = pl.DB_PATH
        pl.DB_PATH = tmp_path / "test.db"

        try:
            init_db(pl.DB_PATH)
            stats = run_pipeline(country_code="US")
            assert stats["inserted"] == 1, f"Expected 1 insert, got {stats}"

            with get_db(pl.DB_PATH) as conn:
                row = conn.execute("SELECT cca2 FROM countries WHERE cca2='US'").fetchone()
                assert row is not None, "US not found in DB after pipeline run"
        finally:
            pl.DB_PATH = original

    def test_pipeline_idempotent(self, tmp_path):
        """Running pipeline twice should update, not duplicate."""
        import sys
        import os
        sys.path.insert(0, os.path.dirname(__file__))
        from pipeline import run_pipeline, get_db, init_db, DB_PATH
        import pipeline as pl

        original = pl.DB_PATH
        pl.DB_PATH = tmp_path / "test_idem.db"

        try:
            init_db(pl.DB_PATH)
            run_pipeline(country_code="DE")
            run_pipeline(country_code="DE")

            with get_db(pl.DB_PATH) as conn:
                count = conn.execute("SELECT COUNT(*) FROM countries").fetchone()[0]
                assert count == 1, f"Expected 1 row after 2 runs, got {count}"
        finally:
            pl.DB_PATH = original
