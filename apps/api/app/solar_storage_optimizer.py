from __future__ import annotations

from typing import Literal

from datetime import datetime, timezone

from app.schemas import SolarStorageOptimizationBatchRequest, SolarStorageOptimizationRequest


def optimize_solar_storage(payload: SolarStorageOptimizationRequest) -> dict:
    horizon_hours = max(payload.dispatchHorizonHours, 0.25)
    load_kw = max(payload.loadKw, 0.0)
    solar_kw = max(payload.solarGenerationKw, 0.0)
    battery_capacity_kwh = max(payload.batteryCapacityKwh, 0.1)
    battery_soc_percent = _clamp(payload.batterySocPercent, 0.0, 100.0)
    battery_max_charge_kw = max(payload.batteryMaxChargeKw, 0.0)
    battery_max_discharge_kw = max(payload.batteryMaxDischargeKw, 0.0)
    import_tariff = max(payload.importTariffRsPerKwh, 0.0)
    export_tariff = max(payload.exportTariffRsPerKwh, 0.0)
    cloud_cover_percent = _clamp(payload.forecastCloudCoverPercent, 0.0, 100.0)
    reserve_floor_percent = _clamp(payload.minReserveSocPercent, 0.0, 95.0)
    peak_threshold = max(payload.peakTariffThresholdRsPerKwh, 0.0)

    cloudy_tomorrow = cloud_cover_percent >= 60.0
    peak_tariff = import_tariff >= peak_threshold
    reserve_target_percent = _reserve_target_percent(
        reserve_floor_percent,
        cloudy_tomorrow=cloudy_tomorrow,
        peak_tariff=peak_tariff,
        current_period=payload.currentPeriod,
    )

    stored_energy_kwh = battery_capacity_kwh * battery_soc_percent / 100.0
    reserve_energy_kwh = battery_capacity_kwh * reserve_target_percent / 100.0
    remaining_capacity_kwh = max(battery_capacity_kwh - stored_energy_kwh, 0.0)
    discharge_headroom_kwh = max(stored_energy_kwh - reserve_energy_kwh, 0.0)

    charge_limit_kw = min(battery_max_charge_kw, remaining_capacity_kwh / horizon_hours)
    discharge_limit_kw = min(battery_max_discharge_kw, discharge_headroom_kwh / horizon_hours)

    solar_to_load_kw = min(solar_kw, load_kw)
    remaining_load_kw = max(load_kw - solar_to_load_kw, 0.0)
    excess_solar_kw = max(solar_kw - solar_to_load_kw, 0.0)
    solar_to_battery_kw = min(excess_solar_kw, charge_limit_kw)
    solar_to_grid_kw = max(excess_solar_kw - solar_to_battery_kw, 0.0)

    battery_share = _battery_share(
        current_period=payload.currentPeriod,
        cloudy_tomorrow=cloudy_tomorrow,
        peak_tariff=peak_tariff,
        battery_soc_percent=battery_soc_percent,
        reserve_target_percent=reserve_target_percent,
    )
    battery_target_kw = remaining_load_kw * battery_share
    battery_to_load_kw = min(remaining_load_kw, discharge_limit_kw, battery_target_kw if battery_share < 1 else discharge_limit_kw)
    grid_to_load_kw = max(remaining_load_kw - battery_to_load_kw, 0.0)

    projected_energy_kwh = _clamp(
        stored_energy_kwh + (solar_to_battery_kw - battery_to_load_kw) * horizon_hours,
        0.0,
        battery_capacity_kwh,
    )
    projected_soc_percent = (projected_energy_kwh / battery_capacity_kwh) * 100.0

    current_strategy = _current_strategy(
        current_period=payload.currentPeriod,
        load_kw=load_kw,
        solar_to_load_kw=solar_to_load_kw,
        solar_to_battery_kw=solar_to_battery_kw,
        battery_to_load_kw=battery_to_load_kw,
        grid_to_load_kw=grid_to_load_kw,
        reserve_target_percent=reserve_target_percent,
        cloudy_tomorrow=cloudy_tomorrow,
        peak_tariff=peak_tariff,
    )
    daytime_strategy = _daytime_strategy(
        reserve_target_percent=reserve_target_percent,
        cloudy_tomorrow=cloudy_tomorrow,
        peak_tariff=peak_tariff,
    )
    nighttime_strategy = _nighttime_strategy(
        reserve_target_percent=reserve_target_percent,
        cloudy_tomorrow=cloudy_tomorrow,
        peak_tariff=peak_tariff,
    )
    recommendations = _recommendations(
        cloudy_tomorrow=cloudy_tomorrow,
        peak_tariff=peak_tariff,
        solar_to_battery_kw=solar_to_battery_kw,
        battery_to_load_kw=battery_to_load_kw,
        grid_to_load_kw=grid_to_load_kw,
        reserve_target_percent=reserve_target_percent,
        export_tariff=export_tariff,
    )

    return {
        "status": "ok",
        "summary": _summary(
            solar_to_load_kw=solar_to_load_kw,
            solar_to_battery_kw=solar_to_battery_kw,
            battery_to_load_kw=battery_to_load_kw,
            grid_to_load_kw=grid_to_load_kw,
            cloudy_tomorrow=cloudy_tomorrow,
            peak_tariff=peak_tariff,
        ),
        "dispatch": {
            "loadKw": _round(load_kw),
            "solarToLoadKw": _round(solar_to_load_kw),
            "solarToBatteryKw": _round(solar_to_battery_kw),
            "solarToGridKw": _round(solar_to_grid_kw),
            "batteryToLoadKw": _round(battery_to_load_kw),
            "gridToLoadKw": _round(grid_to_load_kw),
            "gridSharePercent": _round((grid_to_load_kw / load_kw) * 100.0 if load_kw else 0.0),
        },
        "battery": {
            "currentSocPercent": _round(battery_soc_percent),
            "reserveTargetSocPercent": _round(reserve_target_percent),
            "projectedSocPercent": _round(projected_soc_percent),
            "storedEnergyKwh": _round(stored_energy_kwh),
            "reserveEnergyKwh": _round(reserve_energy_kwh),
            "availableDischargeKw": _round(discharge_limit_kw),
            "availableChargeKw": _round(charge_limit_kw),
        },
        "signals": {
            "currentPeriod": payload.currentPeriod,
            "cloudyTomorrow": cloudy_tomorrow,
            "peakTariff": peak_tariff,
            "weatherRisk": _weather_risk(cloud_cover_percent),
            "tariffBand": "peak" if peak_tariff else "normal",
            "forecastCloudCoverPercent": _round(cloud_cover_percent),
        },
        "strategy": {
            "current": current_strategy,
            "daytime": daytime_strategy,
            "nighttime": nighttime_strategy,
        },
        "recommendations": recommendations,
    }


def optimize_solar_storage_batch(payload: SolarStorageOptimizationBatchRequest) -> dict:
    return {
        "status": "ok",
        "optimizedAt": datetime.now(timezone.utc).isoformat(),
        "results": [
            {
                "buildingId": item.buildingId,
                "buildingName": item.buildingName,
                "optimization": optimize_solar_storage(item.request),
            }
            for item in payload.buildings
        ],
    }


def _reserve_target_percent(
    reserve_floor_percent: float,
    *,
    cloudy_tomorrow: bool,
    peak_tariff: bool,
    current_period: Literal["day", "night"],
) -> float:
    reserve_target = reserve_floor_percent
    if cloudy_tomorrow:
        reserve_target += 15.0
    if peak_tariff:
        reserve_target += 10.0
    if current_period == "night" and cloudy_tomorrow:
        reserve_target += 5.0
    return _clamp(reserve_target, reserve_floor_percent, 90.0)


def _battery_share(
    *,
    current_period: Literal["day", "night"],
    cloudy_tomorrow: bool,
    peak_tariff: bool,
    battery_soc_percent: float,
    reserve_target_percent: float,
) -> float:
    if current_period == "day":
        if cloudy_tomorrow and not peak_tariff:
            share = 0.0
        elif cloudy_tomorrow and peak_tariff:
            share = 0.45
        elif peak_tariff:
            share = 1.0
        else:
            share = 0.6
    else:
        if cloudy_tomorrow and not peak_tariff:
            share = 0.55
        elif cloudy_tomorrow and peak_tariff:
            share = 0.75
        elif peak_tariff:
            share = 1.0
        else:
            share = 0.85

    extra_soc = max(battery_soc_percent - reserve_target_percent, 0.0)
    if extra_soc >= 25.0:
        share += 0.1
    if extra_soc >= 40.0:
        share += 0.1
    return _clamp(share, 0.0, 1.0)


def _summary(
    *,
    solar_to_load_kw: float,
    solar_to_battery_kw: float,
    battery_to_load_kw: float,
    grid_to_load_kw: float,
    cloudy_tomorrow: bool,
    peak_tariff: bool,
) -> str:
    if solar_to_load_kw and solar_to_battery_kw and grid_to_load_kw <= 0.01:
        summary = "Solar is covering demand and charging the battery, so grid import can stay near zero."
    elif battery_to_load_kw and grid_to_load_kw <= 0.01:
        summary = "Battery discharge can cover the remaining demand, which avoids grid import for this window."
    elif grid_to_load_kw and battery_to_load_kw <= 0.01 and cloudy_tomorrow:
        summary = "Use grid for the remaining demand now so the battery stays preserved for tomorrow's cloudy conditions."
    else:
        summary = "Use solar first, blend in battery within the reserve target, and leave the grid as the final fallback."

    if peak_tariff:
        summary += " Peak tariff is active, so expensive grid energy should be avoided where reserve allows."
    return summary


def _current_strategy(
    *,
    current_period: Literal["day", "night"],
    load_kw: float,
    solar_to_load_kw: float,
    solar_to_battery_kw: float,
    battery_to_load_kw: float,
    grid_to_load_kw: float,
    reserve_target_percent: float,
    cloudy_tomorrow: bool,
    peak_tariff: bool,
) -> list[str]:
    actions: list[str] = []
    if solar_to_load_kw > 0:
        actions.append(f"Serve {_round(solar_to_load_kw)} kW of the current {_round(load_kw)} kW load directly from solar.")
    if solar_to_battery_kw > 0:
        actions.append(f"Charge the battery with {_round(solar_to_battery_kw)} kW of surplus solar.")
    if battery_to_load_kw > 0:
        actions.append(f"Discharge {_round(battery_to_load_kw)} kW from the battery to reduce grid import.")
    if grid_to_load_kw > 0:
        actions.append(f"Import only {_round(grid_to_load_kw)} kW from the grid for the remaining demand.")
    if cloudy_tomorrow:
        actions.append(f"Protect at least {_round(reserve_target_percent)}% battery SOC because tomorrow is forecast to be cloudy.")
    if peak_tariff:
        actions.append("Treat this as a peak-tariff window and avoid unnecessary grid draw.")
    if not actions:
        actions.append(f"No dispatch changes are required right now; keep the battery above {_round(reserve_target_percent)}% reserve.")
    if current_period == "night" and solar_to_load_kw <= 0.01:
        actions.insert(0, "Night mode is active, so the battery becomes the preferred source before the grid.")
    return actions


def _daytime_strategy(*, reserve_target_percent: float, cloudy_tomorrow: bool, peak_tariff: bool) -> list[str]:
    actions = [
        "Use solar first to serve daytime load.",
        "Send any excess solar into the battery before exporting to the grid.",
    ]
    if cloudy_tomorrow:
        actions.append(f"Hold the battery above {int(round(reserve_target_percent))}% so energy is saved for tomorrow's weak-solar window.")
    else:
        actions.append("If solar dips below load, discharge the battery within the reserve band before leaning on the grid.")
    if peak_tariff:
        actions.append("During peak tariff, battery discharge should outrank grid import whenever the reserve target is safe.")
    else:
        actions.append("Use the grid only after solar and the planned battery contribution are exhausted.")
    return actions


def _nighttime_strategy(*, reserve_target_percent: float, cloudy_tomorrow: bool, peak_tariff: bool) -> list[str]:
    actions = [
        "At night, shift to battery-first operation within the reserve target.",
        "Use the grid only for the portion that cannot be covered without breaching the battery reserve.",
    ]
    if cloudy_tomorrow:
        actions.append(f"Keep at least {int(round(reserve_target_percent))}% SOC overnight so tomorrow starts with backup energy.")
    else:
        actions.append("Let the battery carry most of the night load to minimize total grid usage.")
    if peak_tariff:
        actions.append("If night pricing is still peak, avoid grid import aggressively and keep the battery as the main source.")
    return actions


def _recommendations(
    *,
    cloudy_tomorrow: bool,
    peak_tariff: bool,
    solar_to_battery_kw: float,
    battery_to_load_kw: float,
    grid_to_load_kw: float,
    reserve_target_percent: float,
    export_tariff: float,
) -> list[dict]:
    recommendations: list[dict] = []

    if cloudy_tomorrow:
        recommendations.append(
            {
                "priority": "high",
                "title": "Save battery for tomorrow",
                "detail": f"Tomorrow's forecast is cloudy, so keep the battery above {int(round(reserve_target_percent))}% instead of draining it fully today.",
            }
        )
    if peak_tariff:
        recommendations.append(
            {
                "priority": "high",
                "title": "Avoid peak grid import",
                "detail": "Grid tariff is in the peak band, so discharge the battery before buying expensive grid energy whenever the reserve target permits.",
            }
        )
    if solar_to_battery_kw > 0:
        recommendations.append(
            {
                "priority": "medium",
                "title": "Capture surplus solar",
                "detail": f"Use {_round(solar_to_battery_kw)} kW of excess solar to charge the battery before considering export.",
            }
        )
    if grid_to_load_kw > 0 and battery_to_load_kw <= 0.01:
        recommendations.append(
            {
                "priority": "medium",
                "title": "Use grid as a reserve-preserving fallback",
                "detail": "Some grid import is intentional here because preserving battery reserve creates a better position for the next risky window.",
            }
        )
    if export_tariff > 0 and solar_to_battery_kw <= 0.01:
        recommendations.append(
            {
                "priority": "low",
                "title": "Export only after storage is full",
                "detail": "Grid export can be allowed, but only after the battery has absorbed the available surplus solar.",
            }
        )

    if not recommendations:
        recommendations.append(
            {
                "priority": "low",
                "title": "Keep the default solar-first policy",
                "detail": "Current conditions are stable, so solar-first with battery support and grid-last remains the right strategy.",
            }
        )
    return recommendations


def _weather_risk(cloud_cover_percent: float) -> str:
    if cloud_cover_percent >= 80.0:
        return "high"
    if cloud_cover_percent >= 55.0:
        return "medium"
    return "low"


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(maximum, max(minimum, value))


def _round(value: float) -> float:
    return round(value, 2)
