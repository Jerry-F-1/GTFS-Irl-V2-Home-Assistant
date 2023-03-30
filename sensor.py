# pylint: disable=no-member, too-many-nested-blocks ,consider-using-dict-items
"""Support for the GTFS Realtime Ireland service."""
from __future__ import annotations

import datetime
import glob
import logging
import os
import sqlite3
import time
from typing import Any

from google.transit import gtfs_realtime_pb2
import pygtfs
import requests
import voluptuous as vol

from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.const import ATTR_LATITUDE, ATTR_LONGITUDE
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.util import Throttle

_LOGGER = logging.getLogger(__name__)

REQUIREMENTS = ["gtfs-realtime-bindings==0.0.7", "protobuf==3.20.1"]

ATTR_STOP_USER_NAME = "Stop User Name"
ATTR_STOP_CODE = "Stop Code"
ATTR_ROUTE = "Route"
ATTR_NEXT_ARRIVAL = "next_arrival"
ATTR_HITS = "arrivals"
ATTR_DEP_TIME = "departure_time"
ATTR_RT_FLAG = "rt_flag"
ATTR_STOP_NAME = "stop_name"
ATTR_STOP_ID = "stop_id"
ATTR_DELAY = "delay"
ATTR_VEHICLE_ID = "vehicle_id"

CONF_API_KEY = "api_key"
CONF_STOP_USER_NAME = "stop_user_name"
CONF_STOP_CODE = "stop_code"
CONF_ROUTE = "route"
CONF_DEPARTURES = "departures"
CONF_OPERATOR = "operator"
CONF_TRIP_UPDATE_URL = "trip_update_url"
CONF_VEHICLE_POSITION_URL = "vehicle_position_url"
CONF_SQL_FILE = "SQL_file_name"
CONF_LIMIT = "arrivals_limit"

DEFAULT_NAME = "gtfs-rt-irl"
DEFAULT_PATH = "gtfs"
ICON = "mdi:bus"

MIN_TIME_BETWEEN_UPDATES = datetime.timedelta(seconds=60)
TIME_STR_FORMAT = "%H:%M"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_TRIP_UPDATE_URL): cv.string,
        vol.Required(CONF_API_KEY): cv.string,
        vol.Required(CONF_SQL_FILE): cv.string,
        vol.Optional(CONF_LIMIT, default=30): vol.Coerce(int),
        vol.Optional(CONF_VEHICLE_POSITION_URL): cv.string,
        vol.Optional(CONF_DEPARTURES): [
            {
                vol.Required(CONF_STOP_USER_NAME): cv.string,
                vol.Required(CONF_STOP_CODE): cv.string,
                vol.Required(CONF_ROUTE): cv.string,
                vol.Required(CONF_OPERATOR): cv.string,
            }
        ],
    }
)


def get_times(route_stops, sqlite_filedb, set_limit):
    """Get the next departure times for today for each required/configured stop, route and operator."""

    conn = sqlite3.connect(sqlite_filedb)
    ctrips = conn.cursor()
    cstoptimes = conn.cursor()
    cstops = conn.cursor()
    cservice = conn.cursor()
    croutes = conn.cursor()
    cexcp = conn.cursor()

    date_format = "%Y-%m-%d %H:%M:%S.%f"
    pattern = "%Y-%m-%d %H:%M:%S.%f"
    pattern1 = "1970-01-01 %H:%M:%S.%f"
    pattern2 = "%Y-%m-%d"

    def validate_service(service_id):
        """Is a service id valid for today with no exceptions."""

        result = False
        today = datetime.datetime.today().weekday()
        cservice.execute(
            "SELECT * from calendar WHERE service_id=:service", {"service": service_id}
        )
        days_of_week = cservice.fetchone()
        today_flag = list(days_of_week)[today + 2]

        today_date = datetime.datetime.today()
        today_date1 = str(today_date)
        today_date2 = datetime.datetime.strftime(today_date, pattern2)
        try:
            d_t = int(time.mktime(time.strptime(today_date1, date_format)))
        except ValueError:
            today_date1 = today_date1 + ".0"
            d_t = int(time.mktime(time.strptime(today_date1, date_format)))
        from_date = list(days_of_week)[9]
        to_date = list(days_of_week)[10]
        dt1 = int(time.mktime(time.strptime(from_date, pattern2)))
        dt2 = int(time.mktime(time.strptime(to_date, pattern2)))

        #    validity = True if d_t >= dt1 and d_t <= dt2 else False
        validity = bool(dt1 <= d_t <= dt2)

        if today_flag == 1 and validity:
            cexcp.execute(
                "SELECT * from calendar_dates WHERE service_id=:service and date=:date",
                {"service": service_id, "date": today_date2},
            )
            exception_date = cexcp.fetchone()
            if exception_date is not None:
                result = False
            else:
                result = True
        return result

    stop_times = []

    for rt_stp in route_stops:
        stop_user_name = rt_stp[0]
        req_stop_code = rt_stp[1]
        req_route = rt_stp[2]
        req_operator = rt_stp[3]

        cstops.execute(
            "SELECT stop_id, stop_code, stop_name from stops WHERE stop_code=:stop",
            {"stop": req_stop_code},
        )

        stop_data = cstops.fetchone()
        req_stop_id = stop_data[0]
        req_stop_name = stop_data[2]

        croutes.execute(
            "SELECT agency_id, route_id from routes WHERE route_short_name=:route AND agency_id=:operator",
            {"route": req_route, "operator": req_operator},
        )

        valid_operator = croutes.fetchone()
        req_route_id = valid_operator[1]

        if valid_operator is not None:
            ctrips.execute(
                "SELECT trip_id, service_id from trips WHERE route_id=:route",
                {"route": req_route_id},
            )

            for trip_id, service_id in ctrips.fetchall():

                req_trip = trip_id
                cstoptimes.execute(
                    "SELECT arrival_time, departure_time, stop_id FROM stop_times WHERE trip_id=:trip AND stop_id=:stop",
                    {"trip": req_trip, "stop": req_stop_id},
                )

                departure = cstoptimes.fetchone()

                if departure is not None:
                    dep_time_str = list(departure)[1]

                    epoch_dep = int(time.mktime(time.strptime(dep_time_str, pattern)))
                    now = datetime.datetime.now()
                    curr_time_str = now.strftime(pattern1)

                    epoch_now = int(time.mktime(time.strptime(curr_time_str, pattern)))

                    if epoch_dep >= epoch_now:
                        diff = epoch_dep - epoch_now

                        if validate_service(service_id):
                            stop_times.append(
                                (
                                    stop_user_name,
                                    req_stop_code,
                                    req_route,
                                    req_trip,
                                    int(diff / 60),
                                    dep_time_str,
                                    req_stop_name,
                                    req_stop_id,
                                )
                            )

    stop_times = sorted(stop_times, key=lambda x: x[4])
    stop_times = stop_times[0:set_limit]

    ctrips.close()
    cstops.close()
    cstoptimes.close()
    cservice.close()
    croutes.close()
    cexcp.close()

    return stop_times


def setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the GTFS Realtime sensor and load the database from the Zip file if needed."""

    target_file = str(config.get(CONF_SQL_FILE))
    gtfs_dir = hass.config.path(DEFAULT_PATH)
    os.makedirs(gtfs_dir, exist_ok=True)

    gtfs_root = gtfs_dir + "/" + target_file
    sqlite_file = f"{gtfs_root}.sqlite?check_same_thread=False"
    sqlite_filedb = f"{gtfs_root}.sqlite"

    if not os.path.exists(sqlite_filedb):

        _LOGGER.error("No SQL file - GTFS Load file %s", sqlite_file)
        gtfs = pygtfs.Schedule(sqlite_file)

        if not gtfs.feeds:

            zip_files = glob.glob(f"{gtfs_dir}/*.zip")
            if not zip_files:
                _LOGGER.error("GTFS schedule zip files not found")
                return

            for zip_data_file in glob.iglob(f"{gtfs_dir}/*.zip"):
                _LOGGER.info("Loading zips")
                pygtfs.append_feed(gtfs, os.path.join(gtfs_dir, zip_data_file))

            conn = sqlite3.connect(sqlite_filedb)
            cursor = conn.cursor()
            create_index = (
                "CREATE INDEX index_stop_times_1 ON stop_times(trip_id, stop_id )"
            )

            cursor.execute(create_index)
            cursor.close()

    trip_url = config.get(CONF_TRIP_UPDATE_URL)
    vehicle_pos_url = config.get(CONF_VEHICLE_POSITION_URL)
    api_key = config.get(CONF_API_KEY)
    set_limit: int | None = config.get(CONF_LIMIT)

    route_deps = []

    for departure in config.get(CONF_DEPARTURES, []):
        stop_user_name = departure.get(CONF_STOP_USER_NAME)
        stop_code = departure.get(CONF_STOP_CODE)
        route = departure.get(CONF_ROUTE)
        operator = departure.get(CONF_OPERATOR)
        route_deps.append((stop_user_name, stop_code, route, operator))

    data = PublicTransportData(
        sqlite_filedb, trip_url, route_deps, vehicle_pos_url, api_key, set_limit
    )

    sensors = []

    for departure in config.get(CONF_DEPARTURES, []):
        stop_user_name = departure.get(CONF_STOP_USER_NAME)
        stop_code = departure.get(CONF_STOP_CODE)
        route = departure.get(CONF_ROUTE)
        operator = departure.get(CONF_OPERATOR)
        sensors.append(
            PublicTransportSensor(
                data, stop_user_name, stop_code, route, latitude=0.00, longitude=0.00
            )
        )

    add_entities(sensors)


class PublicTransportSensor(Entity):
    """Implementation of the GTFS-RT sensor."""

    def __init__(self, data, stop_user_name, stop_code, route_no, latitude, longitude):
        """Initialize the sensor."""
        self.data = data
        self._stop_user_name = stop_user_name
        self._stop_code = stop_code
        self._route_no = route_no
        self._latitude = latitude
        self._longitude = longitude

        self.update()

    @property
    def name(self) -> str:
        """Return the sensor name."""
        return self._stop_user_name

    def _get_next_buses(self):
        return self.data.info.get(self._route_no, {}).get(self._stop_code, [])

    @property
    def state(self) -> str:
        """Return the state of the sensor."""
        next_buses = self._get_next_buses()
        return next_buses[0].arrival_time if len(next_buses) > 0 else "-"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the extra state attributes."""
        next_buses = self._get_next_buses()
        arrivals = str(len(next_buses))
        next_arrival = "-"
        departure_time = "-"
        rt_flag = False
        stop_name = "-"
        stop_id = "-"
        delay = 0
        vehicle_id = "-"

        attrs = {
            ATTR_STOP_USER_NAME: self._stop_user_name,
            ATTR_STOP_CODE: self._stop_code,
            ATTR_ROUTE: self._route_no,
            ATTR_NEXT_ARRIVAL: next_arrival,
            ATTR_HITS: arrivals,
            ATTR_DEP_TIME: departure_time,
            ATTR_RT_FLAG: rt_flag,
            ATTR_STOP_NAME: stop_name,
            ATTR_STOP_ID: stop_id,
            ATTR_DELAY: delay,
            ATTR_VEHICLE_ID: vehicle_id,
        }
        if len(next_buses) > 0:
            attrs[ATTR_DEP_TIME] = next_buses[0].dep_time
            attrs[ATTR_RT_FLAG] = next_buses[0].rt_flag
            attrs[ATTR_STOP_NAME] = next_buses[0].stop_name
            attrs[ATTR_STOP_ID] = next_buses[0].stop_id
            attrs[ATTR_DELAY] = next_buses[0].delay
            attrs[ATTR_VEHICLE_ID] = next_buses[0].vehicle_id

            if next_buses[0].position:
                attrs[ATTR_LATITUDE] = next_buses[0].position.latitude
                # Retain the position in case next polling returns no position.
                self._latitude = next_buses[0].position.latitude
                attrs[ATTR_LONGITUDE] = next_buses[0].position.longitude
                self._longitude = next_buses[0].position.longitude

            else:
                # Restore the last position result, this could cause temporarily incorrect results.
                attrs[ATTR_LATITUDE] = self._latitude
                attrs[ATTR_LONGITUDE] = self._longitude
        if len(next_buses) > 1:
            attrs[ATTR_NEXT_ARRIVAL] = (
                next_buses[1].arrival_time if len(next_buses) > 1 else "-"
            )
        return attrs

    @property
    def unit_of_measurement(self) -> str:
        """Return the unit of the state which is in minutes."""
        return "min"

    @property
    def icon(self) -> str:
        """Icon to use in the frontend, if any."""
        return ICON

    def update(self) -> None:
        """Get the latest data from the static schedule data, realtime feed and update the states."""
        self.data.update()


class PublicTransportData:
    """The Class for handling the data retrieval from the published API."""

    def __init__(
        self,
        sqlite_filedb,
        trip_url,
        route_deps,
        vehicle_position_url,
        api_key=None,
        set_limit=0,
    ):
        """Initialize the info object."""
        self._sqlite_filedb = sqlite_filedb
        self._trip_update_url = trip_url
        self._route_deps = route_deps
        self._vehicle_position_url = vehicle_position_url
        self._set_limit = set_limit

        if api_key is not None:
            self._headers = {"x-api-key": api_key}
        else:
            self._headers = None

        self.info = {}

    @Throttle(MIN_TIME_BETWEEN_UPDATES)
    def update(self):
        """Update for the data object."""
        vehicle_trips = {}
        positions = {}
        if self._vehicle_position_url:
            positions, vehicle_trips = self._get_vehicle_positions()
        self._update_route_statuses(positions, vehicle_trips)

    def _update_route_statuses(self, positions, vehicle_trips):
        """Get the latest data."""

        class StopDetails:
            """Stop times object list.  Position is now implemented."""

            def __init__(
                self,
                stop_user_name,
                arrival_time,
                position,
                dep_time,
                rt_flag,
                stop_name,
                stop_id,
                delay,
                vehicle_id,
            ):
                self.stop_user_name = stop_user_name
                self.arrival_time = arrival_time
                self.position = position
                self.dep_time = dep_time
                self.rt_flag = rt_flag
                self.stop_name = stop_name
                self.stop_id = stop_id
                self.delay = delay
                self.vehicle_id = vehicle_id

        next_times = get_times(self._route_deps, self._sqlite_filedb, self._set_limit)

        feed = gtfs_realtime_pb2.FeedMessage()
        response = requests.get(
            self._trip_update_url, headers=self._headers, timeout=30
        )
        if response.status_code != 200:
            _LOGGER.error("Updating route status got code %s", response.status_code)
            _LOGGER.error("Updating route status got response %s", response.content)

        feed.ParseFromString(response.content)

        departure_times = {}

        for arrival_data in next_times:
            stop_user_name = arrival_data[0]
            stop_code = arrival_data[1]
            route_no = arrival_data[2]
            trip_no = arrival_data[3]
            modified_time = int(arrival_data[4])
            dep_time = arrival_data[5]
            dep_time = dep_time[10:16]
            stop_name = arrival_data[6]
            stop_id = arrival_data[7]

            rt_flag = False
            delay = 0
            vehicle_id = "-"

            # Modify the arrival time using the delay from the feed and get vehicle id if it is the feed.
            for entity in feed.entity:
                if entity.HasField("trip_update"):
                    if entity.trip_update.trip.trip_id == trip_no:
                        for stop in entity.trip_update.stop_time_update:
                            if stop.HasField("arrival"):
                                if stop.stop_id == stop_id:
                                    vehicle_id = entity.trip_update.vehicle.id
                                    rt_flag = True
                                    delay = int(stop.arrival.delay / 60)
                                    modified_time = modified_time + delay

            # If the vehicle ID in unset, get it from the position polling result
            if vehicle_id == "-":
                vehicle_id = vehicle_trips.get(trip_no)
            vehicle_position = positions.get(vehicle_id)

            if route_no not in departure_times:
                departure_times[route_no] = {}
            if not departure_times[route_no].get(stop_code):
                departure_times[route_no][stop_code] = []
            details = StopDetails(
                stop_user_name,
                modified_time,
                vehicle_position,
                dep_time,
                rt_flag,
                stop_name,
                stop_id,
                delay,
                vehicle_id,
            )
            rt_flag = False
            departure_times[route_no][stop_code].append(details)

        # Sort by arrival time, i.e. modified time
        for route_no in departure_times:
            for stop_code in departure_times[route_no]:
                departure_times[route_no][stop_code].sort(key=lambda t: t.arrival_time)

        self.info = departure_times

    def _get_vehicle_positions(self):

        feed = gtfs_realtime_pb2.FeedMessage()
        response = requests.get(
            self._vehicle_position_url, headers=self._headers, timeout=60
        )
        if response.status_code != 200:
            _LOGGER.error("Updating vehicle positions got %s", response.status_code)
            _LOGGER.error("Updating vehicle positions got %s", response.content)

        feed.ParseFromString(response.content)
        positions = {}
        vehicle_trips = {}

        for entity in feed.entity:
            vehicle = entity.vehicle

            if not vehicle.trip.route_id:
                # No vehicle id is listed
                continue

            positions[vehicle.vehicle.id] = vehicle.position
            vehicle_trips[vehicle.trip.trip_id] = vehicle.vehicle.id

        return positions, vehicle_trips
