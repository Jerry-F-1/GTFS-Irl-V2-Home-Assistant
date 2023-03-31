# Home Assistant Custom Sensor for GTFS Realtime Ireland
This project builds on the work of Zacs https://github.com/zacs/ha-gtfs-rt, the existing GTFS Integration in home assistant https://www.home-assistant.io/integrations/gtfs/ and others to provide a Home Assistant custom transport sensor for GTFS realtime in Ireland.  

This release (Version 2) is intended for Version 2 of GTFS Realtime for Ireland, which went live in March 2023.

Version 2 consumes 2 GTFS realtime feeds supported by the National Transport Authority / Transport For Ireland at:  
trip_update_url: "https://api.nationaltransport.ie/gtfsr/v2/TripUpdates"
vehicle_position_url: "https://api.nationaltransport.ie/gtfsr/v2/Vehicles"

For now the sensor requires a download of the relevant static schedule zip file(s) which the sensor will automatically load into a SQLite database.  A third API is planned in future to automate the updating of static schedule data.
Whereas Version 1 only required a single Zip file covering all of Ireland's schedule data, data for the new version is broken down into individual files for different transport operators, e.g. Dublin Bus and GoAhead Dublin.   
The zip files are available on TFI's website https://www.transportforireland.ie/transitData/PT_Data.html 
Further details are at the Irish National Transport Authority website https://developer.nationaltransport.ie/

# Setup and Installation

Before starting the installation you will need to install 2 python modules:
* gtfs-realtime-bindings==0.0.7
* protobuf==3.20.1

1. Subscribe to the API on the Transport Authority's web page to obtain the API Token/Key which you will need to access the realtime data.  This is free and takes about 15 mins.
2. Download the relevant static schedule data zip file(s) provided.  You might need more than one file depending on your requirements.
3. There is no need to rename the zip files (unlike version 1), instead the target database file name will be part of the configuration in Home Assistant
4. Create a new directory in your Home Assistant config folder called "gtfs"
5. Upload the schedule data zip files to the gtfs folder 
6. Also create a new folder called "custom_components" and inside that folder create a folder called "gtfs-rt-irl"
7. Download this repository as a Zip file and unzip
6. Copy the unzipped files to the custom_components/gtfs-rt-irl folder
7. Configue the sensor in Home Assistant, see example below
8. Restart Home Assistant.   The sensor will begin loading the database with the static data from the zip file and this will take some time depending on your technical set up, possibly a few hours.

# Configuration

Add the following (example) configuration to your configuration.yaml file.  This example is for 2 bus stops / routes in Dublin.  Each one uses a different operator, i.e. Dublin Bus and Go Ahead.   user_stop_name: must be unique for each departure.

```sensor:
  - platform: gtfs-rt-irl
    trip_update_url: "https://api.nationaltransport.ie/gtfsr/v2/TripUpdates"
    vehicle_position_url: "https://api.nationaltransport.ie/gtfsr/v2/Vehicles"
    api_key: "******** your API key ***************"
    SQL_file_name: "dublin"
    arrivals_limit: 40
    departures:
      - user_stop_name: "Bus 16 Stop 2922"
        stop_code: "2992"
        route: "16"
        operator: "7778019"

      - user_stop_name: "Bus 175 Stop 2967"
	stop_code: "2967"
        route: "175"
        operator: "7778021"
```        
       
# Configuration Variables:

* __trip_update_url__ (_Required_): The production realtime feed URL as provided by the transport authority. 
* __vehicle_position_url__ (Required): The vehicle position realtime feed as provided by the transport authority.
* __api_key__ (_Required_): Provided by the transport authority when you subscribe.
* __SQL_file_file__ (_Required_): The name of the database file in the gtfs folder to contain the static schedule data, e.g. dublin or cork etc..
* __arrivals_limit__ (_Optional default=30_):  The number of arrivals found to be returned, across all the stops required.
* __departures__(_Required_): The list of route / stop / operator combinations of interest.  At least 1 must be specified.
* __stop_user_name__ (_Required_): A user friendly name for the sensor, must be unique.
* __stop_code__ (_Required_): The required Stop Code. This should be an exact copy of the stop_code field in the stops.txt data file. This is usually the bus stop plate number. 
* __route__: (_Required_): The required Route. This should be an exact copy of the route_short_name field in the routes.txt data file
* __operator__: (_Required_): The required operator. This is the agency_id field in the agency.txt data file

# Extra Attributes

The sensor implementation provides some extra state attributes as follows:

* __Stop User Name__: Same as sensor name, useful for setting up template sensors based on the attributes.  
* __Stop Code__: The stop code in the configuration.
* __Route__:   The route ID, useful for verifying the configuration.
* __Next arrival__:  The next arrival at the stop in minutes.  Can be used to set up a separate template sensor.
* __Arrivals__:  The number of arrivals found for this stop/route/operator within the overall limit set.
* __Departure time__:  E.g. 17:00.  If a vehicle is ahead of schedule, the state of the sensor can be negative, which is not much use.
* __RT flag__: An indicator that a realtime feed record was received for this sensor at the last poll.
* __Stop Name__: The stop name used by the transport authority.
* __Stop ID__:  The stop ID as opposed to the name, useful for verifying the configuration. 
* __Delay__: The number of minutes that the arrival is ahead or behind schedule. 
* __Vehicle ID__: The ID of the next arriving vehicle/bus.
* __Latitude__: With Longitude provides the vehicle's last position result from polling
* __Longitude__: With Latitude provides the vehicle's last position result from polling 

# Please Note

* This implementation for Version 2 is provided as is.  I use it for my own local implementation of Home Assistant and for my local buses in Dublin. I haven't done extensive testing but if any issues are found I will make best endeavors to investigate and fix them.
* Position information seems to be intermittent, possibly only transmitted when a bus is stopped at a stop.  This means that the polling cycle of the sensor could miss a position result.  Therefore, I've coded it so that the sensor retains the last polling result until a new position is returned.  In the meantime the bus is moving so the new position could be missed.  If anyone has a view on this, better information, or a correct intrepretation, post a comment in the discussion page.
* For now the static schedule data will need to be updated every so often, which means the SQLite database and Zip files should be deleted.  The replacement Zip file(s) should be uploaded and Home Assistant restarted to re-generate the SQLite database. The plans announced are that V2 will contain 3 APIs in total including a new API to help automate updates to the static schedule data.  I haven't seen any announcement about this as of 30/03/2023.  
