#!/usr/bin/env python3
"""Diagnose the 'last 24h rain/snow' figure: which place it resolved to, and the
hour-by-hour precipitation behind the total.

    python3 precip_check.py            # your configured location
    python3 precip_check.py Alliston   # try a different place name

If the resolved place isn't your town, set location (or weather_lat/weather_lon)
in display_config.json — a wrong match is the usual reason the number looks off.
"""

import os
import sys
import json
import datetime

os.chdir(os.path.dirname(os.path.abspath(__file__)))

from modules.config_utils import load_config


def main():
    cfg = load_config("display_config.json")
    args = [a for a in sys.argv[1:] if not a.startswith("-")]

    # Two numbers = exact coordinates, e.g.  python3 precip_check.py 43.32 -79.95
    nums = []
    for a in args:
        try:
            nums.append(float(a))
        except ValueError:
            nums = []
            break
    if len(nums) == 2:
        cfg = dict(cfg)
        cfg["weather_lat"], cfg["weather_lon"] = nums[0], nums[1]
        print(f"(using coordinates {nums[0]}, {nums[1]} — ignoring configured location)\n")
        args = []

    override = " ".join(args).strip()
    if override:
        cfg = dict(cfg)
        cfg["location"] = override
        cfg["weather_lat"] = cfg["weather_lon"] = ""
        for f in ("precip_cache.json",):
            try:
                os.remove(f)
            except Exception:
                pass

    import requests
    print(f"config location   : {cfg.get('location')!r}")
    print(f"weather_lat/lon   : {cfg.get('weather_lat') or '-'} / {cfg.get('weather_lon') or '-'}")

    from modules.precip_recent import _coords, _load_cache
    cache = _load_cache()
    try:
        lat, lon = _coords(cfg, cache)
    except Exception as e:
        print("Geocoding failed:", e)
        return
    if lat is None:
        print("Could not resolve a location — set weather_lat/weather_lon.")
        return
    pinned = cfg.get("weather_lat") not in (None, "") and cfg.get("weather_lon") not in (None, "")
    if pinned:
        print(f"coordinates       : {lat}, {lon}   (pinned — geocoding skipped)\n")
    else:
        print(f"resolved place    : {cache.get('place', '(cached)')}")
        print(f"coordinates       : {lat}, {lon}")
        print("   -> not your town? Set location or weather_lat/weather_lon "
              "in display_config.json\n")

    # Real gauge observations (Environment Canada) — what the panel prefers.
    try:
        from modules.precip_recent import ec_last_24h
        ec = ec_last_24h(lat, lon)
        if ec:
            precip, rain, code, dist = ec
            print(f"STATION (measured): {precip} mm  (rain {rain} mm)"
                  f"   station {code}, {dist} km away")
        else:
            print("STATION (measured): no Environment Canada gauge reported nearby")
    except Exception as e:
        print("STATION (measured): failed —", e)

    r = requests.get("https://api.open-meteo.com/v1/forecast", params={
        "latitude": lat, "longitude": lon,
        "hourly": "precipitation,rain,showers,snowfall",
        "past_days": 2, "forecast_days": 1, "timezone": "auto"}, timeout=20).json()
    h = r.get("hourly") or {}
    times, pr, sn = h.get("time", []), h.get("precipitation", []), h.get("snowfall", [])
    now = datetime.datetime.now()
    cutoff = now - datetime.timedelta(hours=24)
    print(f"API timezone      : {r.get('timezone')}")
    print(f"local now         : {now.isoformat(timespec='minutes')}")
    print(f"24h window        : {cutoff.strftime('%m-%d %H:%M')} -> {now.strftime('%m-%d %H:%M')}\n")

    tot_r = tot_s = 0.0
    print("hour                 precip   in-window")
    for i, t in enumerate(times):
        try:
            dt = datetime.datetime.fromisoformat(t)
        except Exception:
            continue
        p = (pr[i] if i < len(pr) else 0) or 0
        s = (sn[i] if i < len(sn) else 0) or 0
        inw = cutoff <= dt <= now
        if inw:
            tot_r += p
            tot_s += s
        if p or s:
            print(f"  {t}   {p:5.2f} mm  {'<-- counted' if inw else '(outside window)'}")
    print(f"\nLAST 24h TOTAL: {round(tot_r,1)} mm rain / {round(tot_s,1)} cm snow")
    try:
        from modules.precip_recent import summary_line
        print(f"panel would show: {summary_line(cfg)!r}")
    except Exception as e:
        print("summary failed:", e)


if __name__ == "__main__":
    main()
