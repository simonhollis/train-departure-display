import os
import re
from typing import Dict, Union

# validate platform number
def parsePlatformData(platform):
    if platform is None:
        return ""
    elif bool(re.match(r'^(?:\d{1,2}[A-D]|[A-D]|\d{1,2})$', platform)):
        return platform
    else:
        return ""

def loadConfig():
    data = {
        "journey": {},
        "api": {}
    }

    data["targetFPS"] = int(os.getenv("targetFPS") or 70)
    data["refreshTime"] = int(os.getenv("refreshTime") or 180)
    data["fpsTime"] = int(os.getenv("fpsTime") or 180)
    data["screenRotation"] = int(os.getenv("screenRotation") or 2)
    data["screenBlankHours"] = os.getenv("screenBlankHours") or ""
    data["headless"] = False
    if os.getenv("headless") == "True":
        data["headless"] = True

    data["debug"] = False
    if os.getenv("debug") == "True":
        data["debug"] = True
    else:
        if os.getenv("debug") and os.getenv("debug").isnumeric():
            data["debug"] = int(os.getenv("debug"))

    data["dualScreen"] = False
    if os.getenv("dualScreen") == "True":
        data["dualScreen"] = True
    data["firstDepartureBold"] = True
    if os.getenv("firstDepartureBold") == "False":
        data["firstDepartureBold"] = False
    data["hoursPattern"] = re.compile("^((2[0-3]|[0-1]?[0-9])-(2[0-3]|[0-1]?[0-9]))$")

    data["journey"]["departureStation"] = os.getenv("departureStation") or "PAD"

    data["journey"]["destinationStation"] = os.getenv("destinationStation") or ""
    if data["journey"]["destinationStation"] == "null" or data["journey"]["destinationStation"] == "undefined":
        data["journey"]["destinationStation"] = ""
    
    data["journey"]["callingAtStation"] = os.getenv("callingAtStation") or ""
    if data["journey"]["callingAtStation"] == "null" or data["journey"]["callingAtStation"] == "undefined":
        data["journey"]["callingAtStation"] = ""

    # Set arrivalStation and departureStation to look for all arrivals at a specific spot from a certain location
    data["journey"]["arrivalStation"] = os.getenv("arrivalStation") or ""
    if data["journey"]["arrivalStation"] == "null" or data["journey"]["arrivalStation"] == "undefined":
        data["journey"]["arrivalStation"] = ""


    data["journey"]["individualStationDepartureTime"] = False
    if os.getenv("individualStationDepartureTime") == "True":
        data["journey"]["individualStationDepartureTime"] = True

    data["journey"]["outOfHoursName"] = os.getenv("outOfHoursName") or "London Paddington"
    data["journey"]["stationAbbr"] = {"International": "Intl."}
    data["journey"]['timeOffset'] = os.getenv("timeOffset") or "0"
    data["journey"]["screen1Platform"] = parsePlatformData(os.getenv("screen1Platform"))
    data["journey"]["screen2Platform"] = parsePlatformData(os.getenv("screen2Platform"))

    data["api"]["apiKey"] = os.getenv("apiKey") or None
    data["api"]["operatingHours"] = os.getenv("operatingHours") or ""

    data["showDepartureNumbers"] = False
    if os.getenv("showDepartureNumbers") == "True":
        data["showDepartureNumbers"] = True

    return data
