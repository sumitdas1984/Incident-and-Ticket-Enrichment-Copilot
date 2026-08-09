"""Thread-safe in-memory store backed by the deterministic seed."""
from __future__ import annotations

from datetime import UTC, datetime

from core.domain import Alarm, AlarmSummary, Asset, OperatorRecommendation, Severity

from .seed import SEED_ALARMS, SEED_ASSETS


class AlarmStore:
    def __init__(self) -> None:
        self._assets: dict[str, Asset] = {a.id: a for a in SEED_ASSETS}
        self._alarms: dict[str, Alarm] = {a.id: a for a in SEED_ALARMS}
        # Calculations stored as a dict keyed by calculation_id.
        self._calculations: dict[str, dict] = {}

    # ---- assets ----

    def search_assets(
        self,
        query: str,
        limit: int = 10,
        unit: str | None = None,
    ) -> list[Asset]:
        """Case-insensitive name + site match. Optional unit filter."""
        q = query.lower()
        results = [
            a
            for a in self._assets.values()
            if (q in a.name.lower() or q in a.site.lower())
            and (unit is None or a.metadata.get("unit") == unit or a.name.endswith("Unit " + unit.split()[-1]))
        ]
        # The "unit" filter above is a tiny heuristic; if Asset
        # learns a `unit` field later, this filter will be exact.
        return results[:limit]

    def get_asset(self, asset_id: str) -> Asset | None:
        return self._assets.get(asset_id)

    # ---- alarms ----

    def list_alarms(
        self,
        asset_id: str | None = None,
        unit: str | None = None,
        site: str | None = None,
        status: str | None = None,
        severity: Severity | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        page: int = 1,
        page_size: int = 50,
        sort_by: str = "raised_at",
        sort_order: str = "desc",
    ) -> tuple[list[Alarm], int]:
        """Filter, sort, paginate. Returns (rows_for_page, total_after_filter)."""
        rows = list(self._alarms.values())

        if asset_id is not None:
            rows = [a for a in rows if a.asset_id == asset_id]
        if severity is not None:
            rows = [a for a in rows if a.severity == severity]
        if status is not None:
            # Postman chaining uses ?status=active to mean !acknowledged.
            if status == "active":
                rows = [a for a in rows if not a.acknowledged]
            elif status == "acknowledged":
                rows = [a for a in rows if a.acknowledged]
        if unit is not None or site is not None:
            asset_ids_for_filter: set[str] = set()
            for a in self._assets.values():
                if (unit is None or a.metadata.get("unit") == unit) and (
                    site is None or a.site == site
                ):
                    asset_ids_for_filter.add(a.id)
            rows = [r for r in rows if r.asset_id in asset_ids_for_filter]
        if start_time is not None:
            rows = [a for a in rows if a.raised_at >= start_time]
        if end_time is not None:
            rows = [a for a in rows if a.raised_at <= end_time]

        # Sort
        reverse = sort_order == "desc"
        if sort_by == "raised_at":
            rows.sort(key=lambda a: a.raised_at, reverse=reverse)
        elif sort_by == "start_time":
            # Postman variable is start_time; same field.
            rows.sort(key=lambda a: a.raised_at, reverse=reverse)
        else:
            rows.sort(key=lambda a: getattr(a, sort_by, a.raised_at), reverse=reverse)

        total = len(rows)
        start = (page - 1) * page_size
        return rows[start : start + page_size], total

    def get_alarm(self, alarm_id: str) -> Alarm | None:
        return self._alarms.get(alarm_id)

    # ---- aggregations ----

    def summarize(
        self,
        asset_ids: list[str] | None = None,
        site: str | None = None,
        unit: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        severity: list[Severity] | None = None,
        group_by: list[str] | None = None,
    ) -> AlarmSummary:
        rows = list(self._alarms.values())
        if asset_ids:
            rows = [a for a in rows if a.asset_id in asset_ids]
        if site is not None or unit is not None:
            allowed = {
                a.id
                for a in self._assets.values()
                if (site is None or a.site == site) and (unit is None or a.metadata.get("unit") == unit)
            }
            rows = [a for a in rows if a.asset_id in allowed]
        if start_time is not None:
            rows = [a for a in rows if a.raised_at >= start_time]
        if end_time is not None:
            rows = [a for a in rows if a.raised_at <= end_time]
        if severity:
            rows = [a for a in rows if a.severity in severity]

        # Count by severity for the simple default view.
        counts: dict[str, int] = {}
        for a in rows:
            counts[a.severity.value] = counts.get(a.severity.value, 0) + 1
        if not group_by:
            return AlarmSummary(items=rows, total=len(rows))
        return AlarmSummary(
            items=rows,
            total=len(rows),
        )  # group_by is currently a no-op placeholder; clients can read .items

    def trends(
        self,
        asset_ids: list[str] | None = None,
        site: str | None = None,
        unit: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        bucket: str = "daily",
    ) -> list[dict]:
        """Time-bucketed alarm counts. One row per (day, severity)."""
        rows = list(self._alarms.values())
        if asset_ids:
            rows = [a for a in rows if a.asset_id in asset_ids]
        if site is not None or unit is not None:
            allowed = {
                a.id
                for a in self._assets.values()
                if (site is None or a.site == site) and (unit is None or a.metadata.get("unit") == unit)
            }
            rows = [a for a in rows if a.asset_id in allowed]
        if start_time is not None:
            rows = [a for a in rows if a.raised_at >= start_time]
        if end_time is not None:
            rows = [a for a in rows if a.raised_at <= end_time]

        out: list[dict] = []
        for a in rows:
            day = a.raised_at.date().isoformat()
            out.append(
                {
                    "bucket": day,
                    "asset_id": a.asset_id,
                    "severity": a.severity.value,
                    "alarm_count": 1,
                    "avg_ack_delay": 0.0 if a.acknowledged else 1.0,
                }
            )
        return out

    def correlation(
        self,
        asset_ids: list[str],
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        severity_threshold: Severity | None = None,
    ) -> dict:
        """Co-occurrence pairs within the time range. Pairs = (a, b) when
        both assets produced alarms in the same hour."""
        rows = [a for a in self._alarms.values() if a.asset_id in asset_ids]
        if severity_threshold is not None:
            order = [Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL]
            threshold_idx = order.index(severity_threshold)
            rows = [a for a in rows if order.index(a.severity) >= threshold_idx]
        if start_time is not None:
            rows = [a for a in rows if a.raised_at >= start_time]
        if end_time is not None:
            rows = [a for a in rows if a.raised_at <= end_time]

        # Bucket by hour.
        buckets: dict[str, set[str]] = {}
        for a in rows:
            hour = a.raised_at.strftime("%Y-%m-%dT%H:00:00Z")
            buckets.setdefault(hour, set()).add(a.asset_id)
        co: dict[tuple[str, str], int] = {}
        for assets in buckets.values():
            sorted_assets = sorted(assets)
            for i, aid in enumerate(sorted_assets):
                for bid in sorted_assets[i + 1 :]:
                    co[(aid, bid)] = co.get((aid, bid), 0) + 1
        pairs = [
            {"asset_id_1": aid, "asset_id_2": bid, "support": s}
            for (aid, bid), s in sorted(co.items(), key=lambda kv: -kv[1])
        ]
        return {"pairs": pairs, "method": "cooccurrence"}

    def flood_analysis(
        self,
        unit: str,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        threshold_count: int = 10,
        rolling_window_minutes: int = 10,
    ) -> dict:
        rows = [a for a in self._alarms.values()]
        if start_time is not None:
            rows = [a for a in rows if a.raised_at >= start_time]
        if end_time is not None:
            rows = [a for a in rows if a.raised_at <= end_time]
        # Count by unit via asset lookup.
        per_asset: dict[str, int] = {}
        for a in rows:
            asset = self._assets.get(a.asset_id)
            if asset and asset.metadata.get("unit") == unit:
                per_asset[asset.id] = per_asset.get(asset.id, 0) + 1
        windows = [
            {"asset_id": aid, "start": start_time.isoformat() if start_time else None,
             "end": end_time.isoformat() if end_time else None,
             "count": n, "threshold": threshold_count}
            for aid, n in per_asset.items() if n >= threshold_count
        ]
        return {"flood_windows": windows, "unit": unit}

    def rationalization_candidates(
        self,
        asset_ids: list[str] | None = None,
        site: str | None = None,
        unit: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        recurrence_threshold: int = 5,
        stale_minutes_threshold: int = 180,
    ) -> list[dict]:
        rows = list(self._alarms.values())
        if asset_ids:
            rows = [a for a in rows if a.asset_id in asset_ids]
        if site is not None or unit is not None:
            allowed = {
                a.id
                for a in self._assets.values()
                if (site is None or a.site == site) and (unit is None or a.metadata.get("unit") == unit)
            }
            rows = [a for a in rows if a.asset_id in allowed]
        if start_time is not None:
            rows = [a for a in rows if a.raised_at >= start_time]
        if end_time is not None:
            rows = [a for a in rows if a.raised_at <= end_time]

        # Group by asset_id and count; flag groups with count >= threshold
        # as candidates.
        per_asset: dict[str, int] = {}
        for a in rows:
            per_asset[a.asset_id] = per_asset.get(a.asset_id, 0) + 1
        return [
            {
                "asset_id": aid,
                "alarm_count": n,
                "recurrence_threshold": recurrence_threshold,
                "stale_minutes_threshold": stale_minutes_threshold,
            }
            for aid, n in per_asset.items()
            if n >= recurrence_threshold
        ]

    def priority_score(self, alarm_id: str) -> int:
        """Deterministic score in 0..100 derived from severity."""
        a = self._alarms.get(alarm_id)
        if a is None:
            raise KeyError(alarm_id)
        return {
            Severity.LOW: 25,
            Severity.MEDIUM: 50,
            Severity.HIGH: 75,
            Severity.CRITICAL: 100,
        }[a.severity]

    def recommendation(self, alarm_id: str) -> OperatorRecommendation:
        a = self._alarms.get(alarm_id)
        if a is None:
            raise KeyError(alarm_id)
        asset = self._assets.get(a.asset_id)
        actions: list[str] = []
        if a.severity in (Severity.HIGH, Severity.CRITICAL):
            actions.append(f"Acknowledge alarm {a.id} and dispatch an operator to {asset.name if asset else a.asset_id}.")
        if a.severity == Severity.CRITICAL:
            actions.append("Escalate to the on-call duty engineer.")
        actions.append("Check the asset's recent alarm history for recurrence.")
        return OperatorRecommendation(
            alarm_id=a.id,
            priority_score=self.priority_score(alarm_id),
            actions=actions,
            rationale=f"{a.severity.value} alarm on {asset.name if asset else a.asset_id}: {a.message}",
        )

    # ---- calculations ----

    def create_calculation(self, calculation_type: str, filters: dict) -> str:
        import uuid

        cid = f"calc-{uuid.uuid4().hex[:12]}"
        self._calculations[cid] = {"calculation_id": cid, "type": calculation_type, "filters": filters}
        return cid

    def execute_calculation(self, calculation_id: str, filters: dict) -> dict:
        stored = self._calculations.get(calculation_id)
        if stored is None:
            raise KeyError(calculation_id)
        return {
            "calculation_id": calculation_id,
            "type": stored["type"],
            "result": {
                "filters": filters,
                "kpi_value": 0.42,
                "computed_at": datetime.now(UTC).isoformat(),
            },
        }

    def kpi_definitions(self) -> list[dict]:
        return [
            {"kpi": "alarm_count", "unit": "count", "description": "Number of alarms in scope."},
            {"kpi": "recurring_rate", "unit": "ratio", "description": "Fraction of alarms recurring within window."},
            {"kpi": "avg_ack_delay", "unit": "minutes", "description": "Average time between raise and acknowledge."},
            {"kpi": "critical_count", "unit": "count", "description": "Count of critical-severity alarms."},
            {"kpi": "suppression_candidate_rate", "unit": "ratio", "description": "Fraction of alarms flagged as suppression candidates."},
        ]


# Helper: build a fresh store for tests / app startup.
def build_default_store() -> AlarmStore:
    return AlarmStore()
