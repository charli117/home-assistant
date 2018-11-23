# coding=utf-8

import asyncio
import hashlib
import json
import logging
import random
import time
import requests
import voluptuous as vol
from datetime import timedelta

from datetime import timedelta
from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.const import TEMP_CELSIUS
from homeassistant.helpers.entity import Entity
from homeassistant.const import (
    CONF_NAME, CONF_MONITORED_CONDITIONS, CONF_SCAN_INTERVAL)
from homeassistant.helpers.event import async_track_time_interval
import homeassistant.helpers.config_validation as cv

_LOGGER = logging.getLogger(__name__)

#同步心跳时间
SCAN_INTERVAL = timedelta(seconds=1200)

#定义客户端
USER_AGENT = 'ColorfulCloudsPro/3.2.2 (iPhone; iOS 11.3; Scale/3.00)'

#定义传感器参数属性
SENSOR_TYPES = {
    'tvoc': ('tvoc', None, 'blur-linear'),                 #有机污染物
    'temp': ('temp', '°C', 'thermometer-lines'),    #温度
    'hcho': ('hcho', 'mg/m3', 'blur-radial'),              #甲醛
    'pm25': ('pm25', 'μg/m³', 'blur'),                     #PM2.5
    'co2': ('co2', 'ppm', 'blur-radial'),                   #二氧化碳浓度
    'humi': ('humi', '%', 'water-percent'),            #湿度
    'lux': ('lux', 'lm', 'white-balance-sunny')            #光照强度
}

#初始化输入参数
CONF_MAC = 'hass_mac'
CONF_APP_KEY = 'hass_app_key'
CONF_SECRET = 'hass_secret'

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Optional(CONF_NAME, default='fengwen'): cv.string,
    vol.Optional(CONF_MAC): cv.string,
    vol.Optional(CONF_APP_KEY): cv.string,
    vol.Optional(CONF_SECRET): cv.string,
    vol.Optional(CONF_MONITORED_CONDITIONS,
        default=['tvoc', 'temp', 'hcho', 'pm25', 'co2', 'humi', 'lux']):
        vol.All(cv.ensure_list, vol.Length(min=1), [vol.In(SENSOR_TYPES)]),
    vol.Optional(CONF_SCAN_INTERVAL, default=timedelta(seconds=1200)): (
        vol.All(cv.time_period, cv.positive_timedelta)),
})

#md5加密文本
def md5(str):
    m = hashlib.md5()
    m.update(str.encode("utf8"))
    return m.hexdigest()

#读取配置文件参数
async def async_setup_platform(hass, config, async_add_devices,discovery_info=None):
    """Set up the fengwen sensor."""
    name = config.get(CONF_NAME)
    hass_mac = str(config.get(CONF_MAC))
    hass_app_key = str(config.get(CONF_APP_KEY))
    hass_secret = str(config.get(CONF_SECRET))
    monitored_conditions = config[CONF_MONITORED_CONDITIONS]
    scan_interval = config.get(CONF_SCAN_INTERVAL)

    fengwen = FengWenData(hass, hass_mac, hass_app_key, hass_secret)
    await fengwen.update_data()

    sensors = []
    for type in monitored_conditions:
        sensors.append(AirQualitySensor(name, type, fengwen))
    async_add_devices(sensors)

    fengwen.sensors = sensors
    async_track_time_interval(hass, fengwen.async_update, scan_interval)

#定义传感器参数
class AirQualitySensor(Entity):
    """Representation of a Sensor."""

    def __init__(self, name, type, fengwen):
        """Initialize the sensor."""
        tname, unit, icon = SENSOR_TYPES[type]
        #self._state = None
        self._name = name + '_' + tname
        self._type = type
        self._unit = unit
        self._icon = icon
        self._fengwen = fengwen

    @property
    def name(self):
        return self._name

    @property
    def icon(self):
        icon = self._icon
        return 'mdi:' + icon

    @property
    def unit_of_measurement(self):
        return self._unit

    @property
    def device_class(self):
        """Return the class of this device, from component DEVICE_CLASSES."""
        if self._type == 'temperature' or self._type == 'humidity':
            return self._type
        return None

    @property
    def available(self):
        return self._type in self._fengwen.data

    @property
    def state(self):
        return self.state_from_data(self._fengwen.data)

    @property
    def state_attributes(self):
        return None

    @property
    def should_poll(self):  # pylint: disable=no-self-use
        """No polling needed."""
        return False

    def state_from_data(self, data):
        return data[self._type] if self._type in data else None

class FengWenData:
    """Class for handling the data retrieval."""
    def __init__(self, hass, hass_mac, hass_app_key, hass_secret):
        """Initialize the data object."""
        self._hass = hass
        self._mac = hass_mac
        self._app_key = hass_app_key
        self._secret = hass_secret
        self.data = {}

    async def async_update(self, time):
        """Update online data and update ha state."""
        old_data = self.data
        await self.update_data()

        tasks = []
        for sensor in self.sensors:
            if sensor.state != sensor.state_from_data(old_data):
                _LOGGER.info('%s: => %s', sensor.name, sensor.state)
            tasks.append(sensor.async_update_ha_state())

        if tasks:
            await asyncio.wait(tasks, loop=self._hass.loop)

    async def update_data(self):
        """Update online data."""
        data = {}
        strsign = md5(str(int((time.time()) * 1000)) + str((self._app_key).upper()) + str((self._mac).upper()) + str((self._secret).upper()))

        try:
            headers = {'User-Agent': USER_AGENT,
                       'Content-Type': 'application/x-www-form-urlencoded',
                       'Accept-Language': 'zh-Hans-CN;q=1'}
            url = "http://wx.iotplc.cn/Api/Device/PullData"
            payload = "mac=%s&app_key=%s&sign=%s&timestamp=%d" % (str(self._mac), str(self._app_key), str(strsign), int((time.time())*1000))
            session = self._hass.helpers.aiohttp_client.async_get_clientsession()
            async with session.post(url, data=payload, headers=headers) as response:
                json = await response.json()
            _LOGGER.info('getReturnData: %s', json)

            result = json['data']
            if json['state'] != 'SIGN_OK':
                raise

            data['tvoc'] = int(result['tvoc'])

            if int(result['tvoc']) >= 0 and int(result['tvoc']) <= 25:
                data['tvoc'] = '优'
            elif int(result['tvoc']) >= 26 and int(result['tvoc']) <= 50:
                data['tvoc'] = '良'
            elif int(result['tvoc']) >= 51 and int(result['tvoc']) <= 75:
                data['tvoc'] = '中'
            else:
                data['tvoc'] = '差'

            data['temp'] = int(result['temp'])
            data['hcho'] = int(result['hcho'])/100
            if int(result['pm25']) > 0 :
                data['pm25'] = int(result['pm25'])
            else:
                data['pm25'] = 0
            if int(result['co2']) > 0 :
                data['co2'] = int(result['co2'])
            else:
                data['co2'] = 0
            data['humi'] = int(result['humi'])
            data['lux'] = int(result['lux'])
        except:
            import traceback
            _LOGGER.error('exception: %s', traceback.format_exc())

        self.data = data