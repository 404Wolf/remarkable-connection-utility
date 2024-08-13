'''
battery.py
This battery model serves as a control point for power information.

RCU is a management client for the reMarkable Tablet.
Copyright (C) 2020-23  Davis Remmel

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as
published by the Free Software Foundation, either version 3 of the
License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
'''

import log
import time


class BatteryRMGeneric:
    @classmethod
    def from_model(cls, model):
        # Initialize for the model-specific battery.
        real_model = model.device_info['model']
        if 'RM100' == real_model or 'RM102' == real_model:
            return BatteryRM1(model)
        if 'RM110' == real_model:
            return BatteryRM2(model)
        log.error('model not recognized: cannot get display')
        return None

    def __init__(self):
        pass


class ProtoBattery:
    linux_ps_cmd = ''
    
    def __init__(self, model):
        self.model = model
        self.info = {}
        self.last_updated = None
        
    def update(self):
        if not self._info_is_outdated():
            return
        log.info('fetching battery info')
        out, err = self.model.run_cmd(type(self).linux_ps_cmd)
        if len(err):
            log.error('error getting battery information')
            log.error(err)
            return
        out_dict = {}
        for line in out.splitlines():
            s = line.split('=')
            key = s[0]
            value = s[1]
            if len(key) and len(value):
                out_dict[key] = value
        self.info = out_dict
        self.last_updated = int(time.time())
        return True

    def _info_is_outdated(self):
        # Update once per 10 seconds
        if not self.last_updated or \
           self.last_updated < (int(time.time()) - 10):
            return True

    def get_status(self):
        self.update()
        linux_key = 'POWER_SUPPLY_STATUS'
        if linux_key in self.info:
            return self.info[linux_key]
        return '---'

    def get_temperature(self):
        self.update()
        linux_key = 'POWER_SUPPLY_TEMP'
        if linux_key in self.info:
            temp_10th_celsius = int(self.info[linux_key])
            deg_c = temp_10th_celsius / 10
            deg_f = deg_c * (9 / 5) + 32
            return '{}℃ ({}℉)'.format(round(deg_c), round(deg_f))
        return '---'

    def get_current_charge(self):
        self.update()
        linux_key = 'POWER_SUPPLY_CHARGE_NOW'
        if linux_key in self.info:
            uah = int(self.info[linux_key])
            mah = uah / 1000
            return '{} mAh'.format(round(mah))
        return '---'

    def get_full_charge(self):
        self.update()
        linux_key = 'POWER_SUPPLY_CHARGE_FULL'
        if linux_key in self.info:
            uah = int(self.info[linux_key])
            mah = uah / 1000
            return '{} mAh'.format(round(mah))
        return '---'

    def get_designed_full_charge(self):
        self.update()
        linux_key = 'POWER_SUPPLY_CHARGE_FULL_DESIGN'
        if linux_key in self.info:
            uah = int(self.info[linux_key])
            mah = uah / 1000
            return '{} mAh'.format(round(mah))
        return '---'

    def get_current_capacity(self):
        self.update()
        linux_key = 'POWER_SUPPLY_CAPACITY'
        if linux_key in self.info:
            return int(self.info[linux_key])
        return 0

    def get_current_health(self):
        self.update()
        linux_key = 'POWER_SUPPLY_CHARGE_FULL_DESIGN'
        if linux_key in self.info:
            uah_charge_full_design = int(self.info[linux_key])
            linux_key = 'POWER_SUPPLY_CHARGE_FULL'
            if linux_key in self.info:
                uah_charge_full = int(self.info[linux_key])
                health = uah_charge_full / uah_charge_full_design * 100
                if health > 100:
                    return 100
                return health
        return 0

    def get_type(self):
        self.update()
        linux_key = 'POWER_SUPPLY_TECHNOLOGY'
        if linux_key in self.info:
            return self.info[linux_key]


class BatteryRM1(ProtoBattery):
    linux_ps_cmd = 'cat /sys/class/power_supply/bq27441-0/uevent'


class BatteryRM2(ProtoBattery):
    linux_ps_cmd = 'cat /sys/class/power_supply/max77818_battery/uevent'
