import requests
import re
import xmltodict
import json
from typing import List, Dict
import datetime


def removeBrackets(originalName):
    return re.split(r" \(", originalName)[0]


def isTime(value):
    matches = re.findall(r"\d{2}:\d{2}", value)
    return len(matches) > 0


def joinwithCommas(listIN):
    return ", ".join(listIN)[::-1].replace(",", "dna ", 1)[::-1]


def removeEmptyStrings(items):
    return filter(None, items)


def joinWith(items, joiner: str):
    filtered_list = removeEmptyStrings(items)
    return joiner.join(filtered_list)


def joinWithSpaces(*args):
    return joinWith(args, " ")


def prepareServiceMessage(operator):
    return joinWithSpaces("A" if operator not in ['Elizabeth Line', 'Avanti West Coast'] else "An", operator, "Service")


def prepareLocationName(location, show_departure_time):
    location_name = removeBrackets(location['lt7:locationName'])

    if not show_departure_time:
        return location_name
    else:
        scheduled_time = location["lt7:st"]
        try:
            expected_time = location["lt7:et"]
        except KeyError:
            # as per api docs, it's 'at' if there isn't an 'et':
            expected_time = location["lt7:at"]
        departure_time = expected_time if isTime(expected_time) else scheduled_time
        formatted_departure = joinWith(["(", departure_time, ")"], "")
        return joinWithSpaces(location_name, formatted_departure)


def prepareCarriagesMessage(carriages):
    if carriages == 0:
        return ""
    else:
        return joinWithSpaces("formed of", carriages, "coaches.")


def ArrivalOrder(ServicesIN):
    ServicesOUT = []
    for servicenum, eachService in enumerate(ServicesIN):
        STDHour = int(eachService['lt4:std'][0:2])
        STDMinute = int(eachService['lt4:std'][3:5])
        if (STDHour < 2):
            STDHour += 24  # this prevents a 12am departure displaying before a 11pm departure
        STDinMinutes = STDHour * 60 + STDMinute  # this service is at this many minutes past midnight
        ServicesOUT.append(eachService)
        ServicesOUT[servicenum]['sortOrder'] = STDinMinutes
    ServicesOUT = sorted(ServicesOUT, key=lambda k: k['sortOrder'])
    return ServicesOUT

def callsAt(target_station, calling_list) -> bool:
    for station_text in calling_list:
        if target_station in station_text:  # i.e. a substring
            return True
    return False


def getDepartureStation(APIElements, boardType):
    return APIElements['soap:Envelope']['soap:Body'][boardType]['GetStationBoardResult']['lt4:locationName']


def getServices(APIElements, boardType):
    Services = []

    

    # if there are only train services from this station
    if 'lt7:trainServices' in APIElements['soap:Envelope']['soap:Body'][boardType]['GetStationBoardResult']:
        Services = APIElements['soap:Envelope']['soap:Body'][boardType]['GetStationBoardResult']['lt7:trainServices']['lt7:service']
        if isinstance(Services, dict):  # if there's only one service, it comes out as a dict
            Services = [Services]       # but it needs to be a list with a single element

        # if there are train and bus services from this station
        if 'lt7:busServices' in APIElements['soap:Envelope']['soap:Body'][boardType]['GetStationBoardResult']:
            BusServices = APIElements['soap:Envelope']['soap:Body'][boardType]['GetStationBoardResult']['lt7:busServices']['lt7:service']
            if isinstance(BusServices, dict):
                BusServices = [BusServices]
            Services = ArrivalOrder(Services + BusServices)  # sort the bus and train services into one list in order of scheduled arrival time

    # if there are only bus services from this station
    elif 'lt7:busServices' in APIElements['soap:Envelope']['soap:Body'][boardType]['GetStationBoardResult']:
        Services = APIElements['soap:Envelope']['soap:Body'][boardType]['GetStationBoardResult']['lt7:busServices']['lt7:service']
        if isinstance(Services, dict):
            Services = [Services]

    else:
        # if there are no trains or buses
        return Services
    return Services


def processCommonFields(thisDeparture, service):
        # next we move elements of dict eachService to dict thisDeparture one by one

        # get platform, if available
        if 'lt4:platform' in service:
            thisDeparture["platform"] = (service['lt4:platform'])

        # get scheduled departure time
        if "lt4:std" in service:
            thisDeparture["aimed_departure_time"] = service["lt4:std"]

        # get estimated departure time
        if "lt4:etd" in service:
            thisDeparture["expected_departure_time"] = service["lt4:etd"]
        
        if "lt4:sta" in service:
            thisDeparture["aimed_arrival_time"] = service["lt4:sta"]

        if "lt4:eta" in service:
            thisDeparture["expected_arrival_time"] = service["lt4:eta"]

        # get carriages, if available
        if 'lt4:length' in service:
            thisDeparture["carriages"] = service["lt4:length"]
        else:
            thisDeparture["carriages"] = 0

        # get operator, if available
        if 'lt4:operator' in service:
            thisDeparture["operator"] = service["lt4:operator"]

        # get name of destination
        if not isinstance(service['lt5:destination']['lt4:location'], list):    # the service only has one destination
            thisDeparture["destination_name"] = removeBrackets(service['lt5:destination']['lt4:location']['lt4:locationName'])
        else:  # the service splits and has multiple destinations
            DestinationList = [i['lt4:locationName'] for i in service['lt5:destination']['lt4:location']]
            thisDeparture["destination_name"] = " & ".join([removeBrackets(i) for i in DestinationList])

def ProcessDepartures(journeyConfig, APIOut, boardType="GetDepBoardWithDetailsResponse"):
    show_individual_departure_time = journeyConfig["individualStationDepartureTime"]
    APIElements = xmltodict.parse(APIOut)
    departureStationName = getDepartureStation(APIElements, boardType)
    Services = getServices(APIElements, boardType)
    if Services == []:
        return None, departureStationName

    # we create a new list of dicts to hold the services
    Departures = [{}] * len(Services)
    for servicenum, eachService in enumerate(Services):
        thisDeparture = {}  # create empty dict to populate
        processCommonFields(thisDeparture, eachService)

        # get via and add to destination name
        if 'lt4:via' in eachService['lt5:destination']['lt4:location']:
           thisDeparture["destination_name"] += " " + eachService['lt5:destination']['lt4:location']['lt4:via']

        callingPoints = None
        if boardType == "GetDepBoardWithDetailsResponse" and "lt7:subsequentCallingPoints" in eachService:
            callingPoints = eachService["lt7:subsequentCallingPoints"]
        elif boardType == "GetArrBoardWithDetailsResponse" and "lt7:previousCallingPoints" in eachService:
            callingPoints = eachService["lt7:previousCallingPoints"]
            
            # get calling points
        if callingPoints is not None:  # there are some calling points
            # check if it is a list of lists    (the train splits, so there are multiple lists of calling points)
            # or a dict                         (the train does not split. There is one list of calling points)
            if not isinstance(callingPoints['lt7:callingPointList'], dict):
                # there are multiple lists of calling points
                CallingPointList = callingPoints['lt7:callingPointList']
                CallLists = []
                CallListJoined = []
                for sectionNum, eachSection in enumerate(CallingPointList):
                    if isinstance(eachSection['lt7:callingPoint'], dict):
                        # there is only one calling point in this list
                        CallLists.append([prepareLocationName(eachSection['lt7:callingPoint'], show_individual_departure_time)])
                        CallListJoined.append(CallLists[sectionNum])
                    else:  # there are several calling points in this list
                        CallLists.append([prepareLocationName(i, show_individual_departure_time) for i in eachSection['lt7:callingPoint']])

                        CallListJoined.append(joinwithCommas(CallLists[sectionNum]))
                        # CallListJoined.append(", ".join(CallLists[sectionNum]))
                thisDeparture["calling_at_list"] = joinWithSpaces(
                    " with a portion going to ".join(CallListJoined),
                    "  --  ",
                    prepareServiceMessage(thisDeparture["operator"]),
                    prepareCarriagesMessage(thisDeparture["carriages"])
                )

            else:  # there is one list of calling points
                if isinstance(callingPoints['lt7:callingPointList']['lt7:callingPoint'], dict):
                    # there is only one calling point in the list
                    thisDeparture["calling_at_list"] = joinWithSpaces(
                        prepareLocationName(callingPoints['lt7:callingPointList']['lt7:callingPoint'], show_individual_departure_time),
                        "only.",
                        "  --  ",
                        prepareServiceMessage(thisDeparture["operator"]),
                        prepareCarriagesMessage(thisDeparture["carriages"])
                    )
                else:  # there are several calling points in the list
                    CallList = [prepareLocationName(i, show_individual_departure_time) for i in callingPoints['lt7:callingPointList']['lt7:callingPoint']]
                    thisDeparture["calling_at_list"] = joinWithSpaces(
                        joinwithCommas(CallList) + ".",
                        " --  ",
                        prepareServiceMessage(thisDeparture["operator"]),
                        prepareCarriagesMessage(thisDeparture["carriages"])
                    )
        else:  # there are no calling points, so just display the destination
            thisDeparture["calling_at_list"] = joinWithSpaces(
                thisDeparture["destination_name"],
                "only.",
                prepareServiceMessage(thisDeparture["operator"]),
                prepareCarriagesMessage(thisDeparture["carriages"])
            )

        Departures[servicenum] = thisDeparture

    return Departures, departureStationName


def processDeparturesForDestination(journeyConfig, APIOut, debug=False):
    """ Used when we filter by calling point """
    debug = True # TODO: REMOVE
    show_individual_departure_time = journeyConfig["individualStationDepartureTime"]
    APIElements = xmltodict.parse(APIOut)
    if "soap:Fault" in APIElements['soap:Envelope']['soap:Body']:
        print(f"soap request resulted in fault")
        return None, None
    
  
    departureStationName = APIElements['soap:Envelope']['soap:Body']["GetNextDeparturesWithDetailsResponse"]["DeparturesBoard"]['lt4:locationName']
    services: Dict[str, Dict[str, Dict]] = APIElements['soap:Envelope']['soap:Body']["GetNextDeparturesWithDetailsResponse"]["DeparturesBoard"]['lt7:departures']
    if debug:
        print("\nDEBUG: API result\n")
        print(APIElements['soap:Envelope']['soap:Body']["GetNextDeparturesWithDetailsResponse"])
        print("\n\nDEBUG: Services\n")
        print(services)
        # Example:  Service {'@crs': 'BTH', 'lt7:service': {'lt4:std': '17:30', 'lt4:etd': 'On time', 'lt4:operator': 'Great Western Railway', 'lt4:operatorCode': 'GW', 'lt4:serviceType': 'train', 'lt4:serviceID': '2220854PADTON__', 'lt5:origin': {'lt4:location': {'lt4:locationName': 'London Paddington', 'lt4:crs': 'PAD'}}, 'lt5:destination': {'lt4:location': {'lt4:locationName': 'Taunton', 'lt4:crs': 'TAU'}}, 'lt7:subsequentCallingPoints': {'lt7:callingPointList': {'lt7:callingPoint': [{'lt7:locationName': 'Reading', 'lt7:crs': 'RDG', 'lt7:st': '17:53', 'lt7:et': 'On time'}, {'lt7:locationName': 'Swindon', 'lt7:crs': 'SWI', 'lt7:st': '18:19', 'lt7:et': 'On time'}, {'lt7:locationName': 'Chippenham', 'lt7:crs': 'CPM', 'lt7:st': '18:32', 'lt7:et': 'On time'}, {'lt7:locationName': 'Bath Spa', 'lt7:crs': 'BTH', 'lt7:st': '18:46', 'lt7:et': 'On time'}, {'lt7:locationName': 'Bristol Temple Meads', 'lt7:crs': 'BRI', 'lt7:st': '19:00', 'lt7:et': 'On time'}, {'lt7:locationName': 'Nailsea & Backwell', 'lt7:crs': 'NLS', 'lt7:st': '19:19', 'lt7:et': 'On time'}, {'lt7:locationName': 'Yatton', 'lt7:crs': 'YAT', 'lt7:st': '19:25', 'lt7:et': 'On time'}, {'lt7:locationName': 'Worle', 'lt7:crs': 'WOR', 'lt7:st': '19:31', 'lt7:et': 'On time'}, {'lt7:locationName': 'Weston Milton', 'lt7:crs': 'WNM', 'lt7:st': '19:35', 'lt7:et': 'On time'}, {'lt7:locationName': 'Weston-super-Mare', 'lt7:crs': 'WSM', 'lt7:st': '19:39', 'lt7:et': 'On time'}, {'lt7:locationName': 'Highbridge & Burnham', 'lt7:crs': 'HIG', 'lt7:st': '19:56', 'lt7:et': 'On time'}, {'lt7:locationName': 'Bridgwater', 'lt7:crs': 'BWT', 'lt7:st': '20:04', 'lt7:et': 'On time'}, {'lt7:locationName': 'Taunton', 'lt7:crs': 'TAU', 'lt7:st': '20:16', 'lt7:et': 'On time'}]}}}}

    departures = []
    departure_sequence = 0
    for service in services.values():
        departure = service['lt7:service']
        details = {}
        if "lt4:platform" in departure:
            details["platform"] = departure["lt4:platform"]
        else:
            details["platform"] = ""

        details["aimed_departure_time"] = departure["lt4:std"]
        details["expected_departure_time"] = departure["lt4:etd"]
        
        if "lt4:length" in departure:
                details["carriages"] = departure["lt4:length"]
        else:
            details["carriages"] = 0

        if departure["lt4:operator"]:
            details["operator"] = departure["lt4:operator"]

        details["destination_name"] = removeBrackets(departure["lt5:destination"]["lt4:location"]["lt4:locationName"])


        if "lt7:subsequentCallingPoints" in departure:
            if isinstance(departure['lt7:subsequentCallingPoints']['lt7:callingPointList']['lt7:callingPoint'], dict):
                # there is only one calling point in the list
                details["calling_at_list"] = joinWithSpaces(
                    prepareLocationName(departure['lt7:subsequentCallingPoints']['lt7:callingPointList']['lt7:callingPoint'], show_individual_departure_time),
                    "only.",
                    "  --  ",
                    prepareServiceMessage(details["operator"]),
                    prepareCarriagesMessage(details["carriages"])
                )
            else:  # there are several calling points in the list
                CallList = [prepareLocationName(i, show_individual_departure_time) for i in departure['lt7:subsequentCallingPoints']['lt7:callingPointList']['lt7:callingPoint']]
                details["calling_at_list"] = joinWithSpaces(
                    joinwithCommas(CallList) + ".",
                    " --  ",
                    prepareServiceMessage(details["operator"]),
                    prepareCarriagesMessage(details["carriages"])
                )
        else:  # there are no calling points, so just display the destination
            details["calling_at_list"] = joinWithSpaces(
                details["destination_name"],
                "only.",
                prepareServiceMessage(details["operator"]),
                prepareCarriagesMessage(details["carriages"])
            )
        
        departures.append(details)
        departure_sequence += 1

    if len(departures) == 0:
        return None, departureStationName
    
    return departures, departureStationName

    exampleResponse = """
{
   "GetNextDeparturesWithDetailsResponse":{
      "@xmlns":"http://thalesgroup.com/RTTI/2017-10-01/ldb/",
      "DeparturesBoard":{
         "@xmlns:lt":"http://thalesgroup.com/RTTI/2012-01-13/ldb/types",
         "@xmlns:lt8":"http://thalesgroup.com/RTTI/2021-11-01/ldb/types",
         "@xmlns:lt6":"http://thalesgroup.com/RTTI/2017-02-02/ldb/types",
         "@xmlns:lt7":"http://thalesgroup.com/RTTI/2017-10-01/ldb/types",
         "@xmlns:lt4":"http://thalesgroup.com/RTTI/2015-11-27/ldb/types",
         "@xmlns:lt5":"http://thalesgroup.com/RTTI/2016-02-16/ldb/types",
         "@xmlns:lt2":"http://thalesgroup.com/RTTI/2014-02-20/ldb/types",
         "@xmlns:lt3":"http://thalesgroup.com/RTTI/2015-05-14/ldb/types",
         "lt4:generatedAt":"2025-05-26T16:04:16.1698386+01:00",
         "lt4:locationName":"London Paddington",
         "lt4:crs":"PAD",
         "lt4:platformAvailable":"true",
         "lt7:departures":{
            "lt7:destination":{
               "@crs":"BTH",
               "lt7:service":{
                  "lt4:std":"16:30",
                  "lt4:etd":"On time",
                  "lt4:operator":"Great Western Railway",
                  "lt4:operatorCode":"GW",
                  "lt4:serviceType":"train",
                  "lt4:serviceID":"2220850PADTON__",
                  "lt5:origin":{
                     "lt4:location":{
                        "lt4:locationName":"London Paddington",
                        "lt4:crs":"PAD"
                     }
                  },
                  "lt5:destination":{
                     "lt4:location":{
                        "lt4:locationName":"Taunton",
                        "lt4:crs":"TAU"
                     }
                  },
                  "lt7:subsequentCallingPoints":{
                     "lt7:callingPointList":{
                        "lt7:callingPoint":[
                           {
                              "lt7:locationName":"Reading",
                              "lt7:crs":"RDG",
                              "lt7:st":"16:53",
                              "lt7:et":"On time"
                           },
                           {
                              "lt7:locationName":"Swindon",
                              "lt7:crs":"SWI",
                              "lt7:st":"17:19",
                              "lt7:et":"On time"
                           },
                           {
                              "lt7:locationName":"Chippenham",
                              "lt7:crs":"CPM",
                              "lt7:st":"17:32",
                              "lt7:et":"On time"
                           },
                           {
                              "lt7:locationName":"Bath Spa",
                              "lt7:crs":"BTH",
                              "lt7:st":"17:44",
                              "lt7:et":"On time"
                           },
                           {
                              "lt7:locationName":"Bristol Temple Meads",
                              "lt7:crs":"BRI",
                              "lt7:st":"17:57",
                              "lt7:et":"On time"
                           },
                           {
                              "lt7:locationName":"Nailsea & Backwell",
                              "lt7:crs":"NLS",
                              "lt7:st":"18:24",
                              "lt7:et":"On time"
                           },
                           {
                              "lt7:locationName":"Yatton",
                              "lt7:crs":"YAT",
                              "lt7:st":"18:30",
                              "lt7:et":"On time"
                           },
                           {
                              "lt7:locationName":"Worle",
                              "lt7:crs":"WOR",
                              "lt7:st":"18:36",
                              "lt7:et":"On time"
                           },
                           {
                              "lt7:locationName":"Weston-super-Mare",
                              "lt7:crs":"WSM",
                              "lt7:st":"18:42",
                              "lt7:et":"On time"
                           },
                           {
                              "lt7:locationName":"Highbridge & Burnham",
                              "lt7:crs":"HIG",
                              "lt7:st":"18:54",
                              "lt7:et":"On time"
                           },
                           {
                              "lt7:locationName":"Bridgwater",
                              "lt7:crs":"BWT",
                              "lt7:st":"19:01",
                              "lt7:et":"On time"
                           },
                           {
                              "lt7:locationName":"Taunton",
                              "lt7:crs":"TAU",
                              "lt7:st":"19:14",
                              "lt7:et":"On time"
                           }
                        ]
                     }
                  }
               }
            }
         }
      }
   }
}
        
        """



def loadDeparturesForStation(journeyConfig, apiKey, rows):
    if journeyConfig["departureStation"] == "":
        raise ValueError(
            "Please configure the departureStation environment variable")

    if apiKey is None:
        raise ValueError(
            "Please configure the apiKey environment variable")

    APIRequest = """
        <x:Envelope xmlns:x="http://schemas.xmlsoap.org/soap/envelope/" xmlns:ldb="http://thalesgroup.com/RTTI/2017-10-01/ldb/" xmlns:typ4="http://thalesgroup.com/RTTI/2013-11-28/Token/types">
        <x:Header>
            <typ4:AccessToken><typ4:TokenValue>""" + apiKey + """</typ4:TokenValue></typ4:AccessToken>
        </x:Header>
        <x:Body>
            <ldb:GetDepBoardWithDetailsRequest>
                <ldb:numRows>""" + rows + """</ldb:numRows>
                <ldb:crs>""" + journeyConfig["departureStation"] + """</ldb:crs>
                <ldb:timeOffset>""" + journeyConfig["timeOffset"] + """</ldb:timeOffset>
                <ldb:filterCrs>""" + journeyConfig["destinationStation"] + """</ldb:filterCrs>
                <ldb:filterType>to</ldb:filterType>
                <ldb:timeWindow>120</ldb:timeWindow>
            </ldb:GetDepBoardWithDetailsRequest>
        </x:Body>
    </x:Envelope>"""

    headers = {'Content-Type': 'text/xml'}
    apiURL = "https://lite.realtime.nationalrail.co.uk/OpenLDBWS/ldb11.asmx"

    APIOut = requests.post(apiURL, data=APIRequest, headers=headers).text

    Departures, departureStationName = ProcessDepartures(journeyConfig, APIOut)

    return Departures, departureStationName



def loadDeparturesForDestination(journeyConfig, apiKey, rows, debug = False):
    if journeyConfig["callingAtStation"] == "" and journeyConfig["destinationStation"] == "":
        raise ValueError(
            "Please configure the callingAtStation or destinationStation environment variable")
    
    # Filter contains contain 1-10 stations
    if journeyConfig["callingAtStation"] != "":
        targetStations = journeyConfig["callingAtStation"]
    else:
        targetStations = journeyConfig["destinationStation"]

    if apiKey is None:
        raise ValueError(
            "Please configure the apiKey environment variable")
    # https://wiki.openraildata.com/index.php/GetNextDeparturesWithDetails
    APIRequest = """
        <x:Envelope xmlns:x="http://schemas.xmlsoap.org/soap/envelope/" xmlns:ldb="http://thalesgroup.com/RTTI/2017-10-01/ldb/" xmlns:typ4="http://thalesgroup.com/RTTI/2013-11-28/Token/types">
        <x:Header>
            <typ4:AccessToken><typ4:TokenValue>""" + apiKey + """</typ4:TokenValue></typ4:AccessToken>
        </x:Header>
        <x:Body>
            <ldb:GetNextDeparturesWithDetailsRequest>
                <ldb:numRows>""" + rows + """</ldb:numRows>
                <ldb:crs>""" + journeyConfig["departureStation"] + """</ldb:crs>
                <ldb:timeOffset>""" + journeyConfig["timeOffset"] + """</ldb:timeOffset>
                <ldb:filterList><ldb:crs>""" + targetStations + """</ldb:crs></ldb:filterList>
                <ldb:timeWindow>120</ldb:timeWindow>
            </ldb:GetNextDeparturesWithDetailsRequest>
        </x:Body>
    </x:Envelope>"""

    headers = {'Content-Type': 'text/xml'}
    apiURL = "https://lite.realtime.nationalrail.co.uk/OpenLDBWS/ldb11.asmx"

    APIOut = requests.post(apiURL, data=APIRequest, headers=headers).text

    Departures, departureStationName = processDeparturesForDestination(journeyConfig, APIOut, debug=debug)

    return Departures, departureStationName



def loadArrivalsAtDestination(journeyConfig, apiKey, rows, debug = False):
    """ Search for all arrivals at 'arrivalStation', coming from 'departureStation' """
    if journeyConfig["arrivalStation"] == "" or journeyConfig["departureStation"] == "":
        raise ValueError(
            "Please configure the arrivalStation and departureStation environment variables")


    services = fetchNdeparturesForDestinations(apiKey, journeyConfig["departureStation"], journeyConfig["arrivalStation"], 0, 5, debug=True)
    if True:
        print("returned services from fetchNdepartures")
        print(services)
        


    if apiKey is None:
        raise ValueError(
            "Please configure the apiKey environment variable")
    # https://wiki.openraildata.com/index.php/GetArrBoardWithDetails
    APIRequest = """
        <x:Envelope xmlns:x="http://schemas.xmlsoap.org/soap/envelope/" xmlns:ldb="http://thalesgroup.com/RTTI/2017-10-01/ldb/" xmlns:typ4="http://thalesgroup.com/RTTI/2013-11-28/Token/types">
        <x:Header>
            <typ4:AccessToken><typ4:TokenValue>""" + apiKey + """</typ4:TokenValue></typ4:AccessToken>
        </x:Header>
        <x:Body>
            <ldb:GetArrBoardWithDetailsRequest>
                <ldb:numRows>""" + rows + """</ldb:numRows>
                <ldb:crs>""" + journeyConfig["arrivalStation"] + """</ldb:crs>
                <ldb:timeOffset>""" + journeyConfig["timeOffset"] + """</ldb:timeOffset>
                <ldb:filterCrs>""" + journeyConfig["departureStation"] + """</ldb:filterCrs>
                <ldb:filterType>from</ldb:filterType>
                <ldb:timeWindow>120</ldb:timeWindow>
            </ldb:GetArrBoardWithDetailsRequest>
        </x:Body>
    </x:Envelope>"""

    headers = {'Content-Type': 'text/xml'}
    apiURL = "https://lite.realtime.nationalrail.co.uk/OpenLDBWS/ldb11.asmx"

    APIOut = requests.post(apiURL, data=APIRequest, headers=headers).text

    # Format is same as departure board
    Departures, departureStationName = ProcessDepartures(journeyConfig, APIOut, boardType="GetArrBoardWithDetailsResponse")

    return Departures, departureStationName


def fetchNdeparturesForDestinations(apiKey, departureStation, destinationStations, timeOffset, num_to_fetch, debug = False):
    debug = True
    if apiKey is None:
        raise ValueError(
            "Please configure the apiKey environment variable")
    services: List[Dict[str, Dict[str, Dict]]] = []
    serviceIds = set()
    timeOffset = str(timeOffset)
    # https://wiki.openraildata.com/index.php/GetNextDeparturesWithDetails
    while len(services) < num_to_fetch:
        if debug:
            print("timeOffset in request is ", timeOffset)
        APIRequest = """
            <x:Envelope xmlns:x="http://schemas.xmlsoap.org/soap/envelope/" xmlns:ldb="http://thalesgroup.com/RTTI/2017-10-01/ldb/" xmlns:typ4="http://thalesgroup.com/RTTI/2013-11-28/Token/types">
            <x:Header>
                <typ4:AccessToken><typ4:TokenValue>""" + apiKey + """</typ4:TokenValue></typ4:AccessToken>
            </x:Header>
            <x:Body>
                <ldb:GetNextDeparturesWithDetailsRequest>
                    <ldb:numRows>""" + "1" + """</ldb:numRows>
                    <ldb:crs>""" + departureStation + """</ldb:crs>
                    <ldb:timeOffset>""" + timeOffset + """</ldb:timeOffset>
                    <ldb:filterList><ldb:crs>""" + destinationStations + """</ldb:crs></ldb:filterList>
                    <ldb:timeWindow>120</ldb:timeWindow>
                </ldb:GetNextDeparturesWithDetailsRequest>
            </x:Body>
        </x:Envelope>"""

        headers = {'Content-Type': 'text/xml'}
        apiURL = "https://lite.realtime.nationalrail.co.uk/OpenLDBWS/ldb11.asmx"

        APIOut = requests.post(apiURL, data=APIRequest, headers=headers).text
        APIElements = xmltodict.parse(APIOut)
        if "soap:Fault" in APIElements['soap:Envelope']['soap:Body']:
            print(f"soap request resulted in fault")
            return None, None
        

        """
        DEBUG: new_services
2025-06-08T22:44:38+01:00  main   {'@crs': 'BTH', 'lt7:service': {'lt4:std': '23:00', 'lt4:etd': 'On time', 'lt4:operator': 'Great Western Railway', 'lt4:operatorCode': 'GW', 'lt4:serviceType': 'train', 'lt4:serviceID': '2633427PADTON__', 'lt5:rsid': 'GW475700', 'lt5:origin': {'lt4:location': {'lt4:locationName': 'London Paddington', 'lt4:crs': 'PAD'}}, 'lt5:destination': {'lt4:location': {'lt4:locationName': 'Bristol Temple Meads', 'lt4:crs': 'BRI'}}, 'lt7:subsequentCallingPoints': {'lt7:callingPointList': {'lt7:callingPoint': [{'lt7:locationName': 'Reading', 'lt7:crs': 'RDG', 'lt7:st': '23:34', 'lt7:et': 'On time'}, {'lt7:locationName': 'Didcot Parkway', 'lt7:crs': 'DID', 'lt7:st': '23:51', 'lt7:et': 'On time'}, {'lt7:locationName': 'Swindon', 'lt7:crs': 'SWI', 'lt7:st': '00:10', 'lt7:et': 'On time'}, {'lt7:locationName': 'Chippenham', 'lt7:crs': 'CPM', 'lt7:st': '00:23', 'lt7:et': 'On time'}, {'lt7:locationName': 'Bath Spa', 'lt7:crs': 'BTH', 'lt7:st': '00:34', 'lt7:et': 'On time'}, {'lt7:locationName': 'Bristol Temple Meads', 'lt7:crs': 'BRI', 'lt7:st': '00:49', 'lt7:et': 'On time'}]}}}}"""


        new_services = APIElements['soap:Envelope']['soap:Body']["GetNextDeparturesWithDetailsResponse"]["DeparturesBoard"]['lt7:departures']['lt7:destination']
        print("DEBUG: new_services\n", new_services)
        if "lt7:service" in new_services:
            #services.update(new_services["lt7:service"])

            # Check for no services
            #  e.g. {'@crs': 'BTH', 'lt7:service': {'@xsi:nil': 'true'}}
            if "@xsi:nil" in new_services['lt7:service'] and new_services["lt7:service"]["@xsi:nil"] == "true":  
                if debug:
                    print("No services found. Returning.")
                return services
            id = new_services["lt7:service"]["lt4:serviceID"]
            if id not in serviceIds:
                serviceIds.add(id)
                service_item = {"lt7:service": new_services["lt7:service"]}
                services.append(service_item)
            else:
                print(f"WARNING: detected duplicate service ID: {id}. Will return now.")
                return services
        else:
            # Assume there are no more services:
            return services
        if debug:
            print("Services now are:\n", services)
        latest_service_time = services[-1]['lt7:service']["lt4:std"]
        if debug:
            print("latest service time is ", latest_service_time)
        # Fetch the service after this one
        latest_hours = latest_service_time[0:2]  # HH:MM
        latest_mins = latest_service_time[3:5]
        now = datetime.datetime.now()
        now_hours = now.strftime("%H")
        now_mins = now.strftime("%M")
   
        # Calculate one minute longer than previous latest departure
        now_mins_since_midnight = (int(now_hours) * 60) + int(now_mins)
        latest_mins_since_midnight = (int(latest_hours) * 60) + int(latest_mins)
        delta_from_now = latest_mins_since_midnight - now_mins_since_midnight + 1  # + 1 to select next service
        if delta_from_now < 0:
            delta_from_now += 24 * 60  # underflow correction
        timeOffset = str(min(120, delta_from_now)) # 120 is maximum request

        if debug:
            print(f"\nNdepartures calculated prev departure time was {latest_service_time} ({latest_hours}:{latest_mins}),\nCurrent time is {now_hours}:{now_mins}, so next request will be for {delta_from_now} mins from current time of day.\ntimeOffset is therefore {timeOffset}\n")

        if debug:
            print("\nDEBUG: API result\n")
            print(APIElements['soap:Envelope']['soap:Body']["GetNextDeparturesWithDetailsResponse"])
            print("\n\nDEBUG: Services\n")
            print("Num services so far: ", len(services))
            print(services)
    return services
        