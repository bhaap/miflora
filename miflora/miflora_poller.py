""""
Read data from Mi Flora plant sensor.

Reading from the sensor is handled by the command line tool "gatttool" that
is part of bluez on Linux.
No other operating systems are supported at the moment
"""

import sys
from datetime import datetime, timedelta
from threading import Lock, current_thread
import logging
import pygatt

MI_TEMPERATURE = "temperature"
MI_LIGHT = "light"
MI_MOISTURE = "moisture"
MI_CONDUCTIVITY = "conductivity"
MI_BATTERY = "battery"


def write_ble(mac, handle, value, retries=10, timeout=20):
    """
    Read from a BLE address

    @param: mac - MAC address in format XX:XX:XX:XX:XX:XX
    @param: handle - BLE characteristics handle in format 0xXX
    @param: value - value to write to the given handle
    @param: timeout - timeout in seconds
    """

    attempt = 0

    while attempt <= retries:

        while True:

            try:
                adapter = pygatt.BGAPIBackend()
                adapter.start()
                device = adapter.connect(mac)
                device.char_write_handle(handle, value)
                adapter.stop()

                return True

            except:
                attempt += 1
                pass

    return False


def read_ble(mac, handle, retries=10, timeout=20):
    """
    Read from a BLE address

    @param: mac - MAC address in format XX:XX:XX:XX:XX:XX
    @param: handle - BLE characteristics handle in format 0xXX
    @param: timeout - timeout in seconds
    """

    attempt = 0

    while attempt <= retries:

        while True:

            try:
                adapter = pygatt.BGAPIBackend()
                adapter.start()
                device = adapter.connect(mac)
                data = device.char_read_handle(handle)
                adapter.stop()

                return data

            except:
                attempt += 1
                pass

    return None

def write_read_ble(mac, retries=10, timeout=20):
    """
    Write and then read sensor data from BLE address

    @param: mac - MAC address in format XX:XX:XX:XX:XX:XX
    @param: handle - BLE characteristics handle in format 0xXX
    @param: timeout - timeout in seconds
    """

    attempt = 0

    while attempt <= retries:

        while True:

            try:
                adapter = pygatt.BGAPIBackend()
                adapter.start()
                device = adapter.connect(mac)
                device.char_write_handle(0x0033, bytearray([0xa0, 0x1f]))
                data=device.char_read_handle(0x0035)
                adapter.stop()

                return data

            except:
                attempt += 1
                pass

    return None


class MiFloraPoller(object):
    """"
    A class to read data from Mi Flora plant sensors.
    """

    def __init__(self, mac, adapter, cache_timeout=600, retries=3):
        """
        Initialize a Mi Flora Poller for the given MAC address.
        """

        self._mac = mac
        self.adapter = adapter
        self._cache = None
        self._cache_timeout = timedelta(seconds=cache_timeout)
        self._last_read = None
        self._fw_last_read = datetime.now()
        self.retries = retries
        self.ble_timeout = 10
        self.lock = Lock()
        self._firmware_version = None

    def name(self):
        """
        Return the name of the sensor.
        """
        name = read_ble(self._mac, 0x0003,
                        retries=self.retries,
                        timeout=self.ble_timeout)
        return ''.join(chr(n) for n in name)

    def fill_cache(self):
        firmware_version = self.firmware_version()
        if not firmware_version:
            # If a sensor doesn't work, wait 5 minutes before retrying
            self._last_read = datetime.now() - self._cache_timeout + \
                timedelta(seconds=300)
            return

        self._cache = write_read_ble(self._mac,
                               retries=self.retries,
                               timeout=self.ble_timeout)
        self._check_data()

        if self._cache is not None:
            self._last_read = datetime.now()

        else:
            # If a sensor doesn't work, wait 5 minutes before retrying
            self._last_read = datetime.now() - self._cache_timeout + \
                timedelta(seconds=300)

    def battery_level(self):
        """
        Return the battery level.

        The battery level is updated when reading the firmware version. This
        is done only once every 24h
        """
        self.firmware_version()
        return self.battery

    def firmware_version(self):
        """ Return the firmware version. """
        if (self._firmware_version is None) or \
                (datetime.now() - timedelta(hours=24) > self._fw_last_read):
            self._fw_last_read = datetime.now()
            res = read_ble(self._mac, 0x0038, retries=self.retries)
            if res is None:
                self.battery = 0
                self._firmware_version = None
            else:
                self.battery = res[0]
                self._firmware_version = "".join(map(chr, res[2:]))
        return self._firmware_version

    def parameter_value(self, parameter, read_cached=True):
        """
        Return a value of one of the monitored paramaters.

        This method will try to retrieve the data from cache and only
        request it by bluetooth if no cached value is stored or the cache is
        expired.
        This behaviour can be overwritten by the "read_cached" parameter.
        """

        # Special handling for battery attribute
        if parameter == MI_BATTERY:
            return self.battery_level()

        # Use the lock to make sure the cache isn't updated multiple times
        with self.lock:
            if (read_cached is False) or \
                    (self._last_read is None) or \
                    (datetime.now() - self._cache_timeout > self._last_read):
                self.fill_cache()
#             else:
#                 LOGGER.debug("Using cache (%s < %s)",
#                              datetime.now() - self._last_read,
#                              self._cache_timeout)

        if self._cache and (len(self._cache) == 16):
            return self._parse_data()[parameter]
        else:
            self.fill_cache()
            raise IOError("Could not read data from Mi Flora sensor %s",
                          self._mac)

    def _check_data(self):
        if self._cache is None:
            return
        if self._cache[7] > 100: # moisture over 100 procent
            self._cache = None
            return
        if self._firmware_version >= "2.6.6":
            if sum(self._cache[10:]) == 0:
                self._cache = None
                return
        if sum(self._cache) == 0:
            self._cache = None
            return None

    def _parse_data(self):
        data = self._cache
        res = {}
        res[MI_TEMPERATURE] = float(data[1] * 256 + data[0]) / 10
        res[MI_MOISTURE] = data[7]
        res[MI_LIGHT] = data[4] * 256 + data[3]
        res[MI_CONDUCTIVITY] = data[9] * 256 + data[8]
        return res
