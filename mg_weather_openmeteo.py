from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Tuple, List

import pandas as pd
import requests


def parseymd(s: str) -> date:
    return datetime.strptime(s.strip(), "%Y-%m-%d").date()


def formatymd(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def adddaysinclusive(startd: date, days: int) -> date:
    return startd + timedelta(days=max(int(days), 1) - 1)


def resolvetimezoneandelevation(lat: float, lon: float, timeout: int = 20) -> Tuple[str, float]:
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": float(lat),
        "longitude": float(lon),
        "timezone": "auto",
        "hourly": "temperature_2m",
        "forecast_days": 1,
    }
    r = requests.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    tz = data.get("timezone", None)
    elev = data.get("elevation", None)
    if not tz:
        raise RuntimeError("Timezone resolve failed.")
    if elev is None:
        raise RuntimeError("Elevation resolve failed.")
    return str(tz), float(elev)


def parseopenmeteohourlydata(data: dict, tz: str) -> pd.DataFrame:
    hourly = pd.DataFrame(data.get("hourly", {}))
    if hourly.empty:
        return hourly
    hourly["time"] = pd.to_datetime(hourly["time"]).dt.tz_localize(tz)
    hourly = hourly.set_index("time")
    return hourly


def parseopenmeteodailydata(data: dict) -> pd.DataFrame:
    dailyraw = data.get("daily", None)
    if not (isinstance(dailyraw, dict) and "time" in dailyraw):
        return pd.DataFrame()
    daily = pd.DataFrame(dailyraw)
    dailytime = pd.to_datetime(daily["time"])
    daily["date"] = dailytime.dt.date
    daily = daily.set_index("date").drop(columns=["time"], errors="ignore")
    return daily


def getweatherdataarchive(lat, lon, startdate, enddate, tz) -> Tuple[pd.DataFrame, pd.DataFrame]:
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": startdate,
        "end_date": enddate,
        "hourly": (
            "temperature_2m,wind_speed_10m,"
            "shortwave_radiation,direct_normal_irradiance,diffuse_radiation,"
            "snowfall,weather_code"
        ),
        "daily": "weather_code,temperature_2m_min,temperature_2m_max",
        "timezone": tz,
    }
    res = requests.get(url, params=params, timeout=30)
    res.raise_for_status()
    data = res.json()
    return parseopenmeteohourlydata(data, tz), parseopenmeteodailydata(data)


def getweatherdataforecast(lat, lon, startdate, enddate, tz) -> Tuple[pd.DataFrame, pd.DataFrame]:
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": startdate,
        "end_date": enddate,
        "hourly": (
            "temperature_2m,wind_speed_10m,"
            "shortwave_radiation,direct_normal_irradiance,diffuse_radiation,"
            "snowfall,weather_code"
        ),
        "daily": "weather_code,temperature_2m_min,temperature_2m_max",
        "timezone": tz,
    }
    res = requests.get(url, params=params, timeout=30)
    res.raise_for_status()
    data = res.json()
    return parseopenmeteohourlydata(data, tz), parseopenmeteodailydata(data)


def getweatherdatamixed(lat, lon, startdate, enddate, tz) -> Tuple[pd.DataFrame, pd.DataFrame]:
    sd = parseymd(startdate)
    ed = parseymd(enddate)
    if ed < sd:
        raise ValueError("End date is earlier than start date.")

    todaylocal = pd.Timestamp.now(tz).date()
    hourlyparts: List[pd.DataFrame] = []
    dailyparts: List[pd.DataFrame] = []

    archiveend = min(ed, todaylocal - timedelta(days=1))
    if sd <= archiveend:
        h, d = getweatherdataarchive(lat, lon, formatymd(sd), formatymd(archiveend), tz)
        if not h.empty:
            hourlyparts.append(h)
        if not d.empty:
            dailyparts.append(d)

    forecaststart = max(sd, todaylocal)
    if forecaststart <= ed:
        h, d = getweatherdataforecast(lat, lon, formatymd(forecaststart), formatymd(ed), tz)
        if not h.empty:
            hourlyparts.append(h)
        if not d.empty:
            dailyparts.append(d)

    hourly = pd.concat(hourlyparts, axis=0) if hourlyparts else pd.DataFrame()
    if not hourly.empty:
        hourly = hourly[~hourly.index.duplicated(keep="last")].sort_index()

    daily = pd.concat(dailyparts, axis=0) if dailyparts else pd.DataFrame()
    if not daily.empty:
        daily = daily[~daily.index.duplicated(keep="last")].sort_index()

    return hourly, daily
