import requests
import re
import xmltodict
import json
from typing import List, Dict


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

def ProcessDepartures(journeyConfig, APIOut):
    show_individual_departure_time = journeyConfig["individualStationDepartureTime"]
    APIElements = xmltodict.parse(APIOut)
    Services = []

    # get departure station name
    departureStationName = APIElements['soap:Envelope']['soap:Body']['GetDepBoardWithDetailsResponse']['GetStationBoardResult']['lt4:locationName']

    # if there are only train services from this station
    if 'lt7:trainServices' in APIElements['soap:Envelope']['soap:Body']['GetDepBoardWithDetailsResponse']['GetStationBoardResult']:
        Services = APIElements['soap:Envelope']['soap:Body']['GetDepBoardWithDetailsResponse']['GetStationBoardResult']['lt7:trainServices']['lt7:service']
        if isinstance(Services, dict):  # if there's only one service, it comes out as a dict
            Services = [Services]       # but it needs to be a list with a single element

        # if there are train and bus services from this station
        if 'lt7:busServices' in APIElements['soap:Envelope']['soap:Body']['GetDepBoardWithDetailsResponse']['GetStationBoardResult']:
            BusServices = APIElements['soap:Envelope']['soap:Body']['GetDepBoardWithDetailsResponse']['GetStationBoardResult']['lt7:busServices']['lt7:service']
            if isinstance(BusServices, dict):
                BusServices = [BusServices]
            Services = ArrivalOrder(Services + BusServices)  # sort the bus and train services into one list in order of scheduled arrival time

    # if there are only bus services from this station
    elif 'lt7:busServices' in APIElements['soap:Envelope']['soap:Body']['GetDepBoardWithDetailsResponse']['GetStationBoardResult']:
        Services = APIElements['soap:Envelope']['soap:Body']['GetDepBoardWithDetailsResponse']['GetStationBoardResult']['lt7:busServices']['lt7:service']
        if isinstance(Services, dict):
            Services = [Services]

    # if there are no trains or buses
    else:
        Services = None
        return None, departureStationName

    # we create a new list of dicts to hold the services
    Departures = [{}] * len(Services)

    for servicenum, eachService in enumerate(Services):
        thisDeparture = {}  # create empty dict to populate

        # next we move elements of dict eachService to dict thisDeparture one by one

        # get platform, if available
        if 'lt4:platform' in eachService:
            thisDeparture["platform"] = (eachService['lt4:platform'])

        # get scheduled departure time
        thisDeparture["aimed_departure_time"] = eachService["lt4:std"]

        # get estimated departure time
        thisDeparture["expected_departure_time"] = eachService["lt4:etd"]

        # get carriages, if available
        if 'lt4:length' in eachService:
            thisDeparture["carriages"] = eachService["lt4:length"]
        else:
            thisDeparture["carriages"] = 0

        # get operator, if available
        if 'lt4:operator' in eachService:
            thisDeparture["operator"] = eachService["lt4:operator"]

        # get name of destination
        if not isinstance(eachService['lt5:destination']['lt4:location'], list):    # the service only has one destination
            thisDeparture["destination_name"] = removeBrackets(eachService['lt5:destination']['lt4:location']['lt4:locationName'])
        else:  # the service splits and has multiple destinations
            DestinationList = [i['lt4:locationName'] for i in eachService['lt5:destination']['lt4:location']]
            thisDeparture["destination_name"] = " & ".join([removeBrackets(i) for i in DestinationList])

        # get via and add to destination name
        # if 'lt4:via' in eachService['lt5:destination']['lt4:location']:
        #    thisDeparture["destination_name"] += " " + eachService['lt5:destination']['lt4:location']['lt4:via']

            # get calling points
        if 'lt7:subsequentCallingPoints' in eachService:  # there are some calling points
            # check if it is a list of lists    (the train splits, so there are multiple lists of calling points)
            # or a dict                         (the train does not split. There is one list of calling points)
            if not isinstance(eachService['lt7:subsequentCallingPoints']['lt7:callingPointList'], dict):
                # there are multiple lists of calling points
                CallingPointList = eachService['lt7:subsequentCallingPoints']['lt7:callingPointList']
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
                if isinstance(eachService['lt7:subsequentCallingPoints']['lt7:callingPointList']['lt7:callingPoint'], dict):
                    # there is only one calling point in the list
                    thisDeparture["calling_at_list"] = joinWithSpaces(
                        prepareLocationName(eachService['lt7:subsequentCallingPoints']['lt7:callingPointList']['lt7:callingPoint'], show_individual_departure_time),
                        "only.",
                        "  --  ",
                        prepareServiceMessage(thisDeparture["operator"]),
                        prepareCarriagesMessage(thisDeparture["carriages"])
                    )
                else:  # there are several calling points in the list
                    CallList = [prepareLocationName(i, show_individual_departure_time) for i in eachService['lt7:subsequentCallingPoints']['lt7:callingPointList']['lt7:callingPoint']]
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
