#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################

import indigo
import logging
import numpy as np
import time
from ghpu import GitHubPluginUpdater

class Plugin(indigo.PluginBase):
    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
        super(Plugin, self).__init__(pluginId, pluginDisplayName, pluginVersion, pluginPrefs)
        self.logger.setLevel(logging.INFO)
        self.parentDevIdsWeUseDict = []
        self.updater = GitHubPluginUpdater(self)

    def startup(self):
        self.setLogLevel()
        self.logger.debug(u"startup called")
        indigo.devices.subscribeToChanges()
        self.parentDevIdsWeUseDict = []

    def shutdown(self):
        self.logger.debug(u"shutdown called")

    def _refreshState(self, dev, logRefresh=False):

        keyValueList = []
        if dev.deviceTypeId == u"virtualDeviceEnergyMeter":
            # TODO: Fix error handling if parentDevice don't exits
            if int(dev.ownerProps[u"parentDeviceId"]) not in indigo.devices:
                self.logger.warn(u"Parent device  does not exits any more ")
                return
            parentDevice = indigo.devices[int(dev.ownerProps[u"parentDeviceId"])]
            ts = time.time()
            if "curEnergyLevel" in dev.states:
                if parentDevice.states['onOffState']:
                    if u"brightnessLevel" in parentDevice.states:
                        watts = self.getCurPower(dev, int(parentDevice.states.get("brightnessLevel")))
                    else:
                        watts = float(dev.ownerProps[u"powerAtOn"])
                    wattsStr = "%.2f W" % (watts)
                    accumEnergyTotalTS = dev.states.get("accumEnergyTotalTS", ts)
                    if accumEnergyTotalTS == 0:
                        accumEnergyTotalTS = ts
                    energy = ((ts - accumEnergyTotalTS) / 3600 * watts) / 1000
                    self._addAccumEnergy(dev, energy, ts)
                else:
                    watts = 0.0
                    wattsStr = "%d W" % (watts)
                    self._addAccumEnergy(dev, 0, ts)
                keyValueList.append(
                    {'key': 'curEnergyLevel', 'value': watts, 'uiValue': wattsStr})
        elif dev.deviceTypeId == u"virtualGroupEnergyMeter" and u"childEnergyMeters" in dev.ownerProps:
            ts = time.time()
            accumEnergyTotalTS = dev.states.get("accumEnergyTotalTS", ts)
            if accumEnergyTotalTS == 0:
                accumEnergyTotalTS = ts
            watts = 0.0
            power = 0.0
            for devId in dev.ownerProps[u"childEnergyMeters"]:
                if int(devId) in indigo.devices:
                    childWatt = indigo.devices[int(devId)].states.get('curEnergyLevel', 0)
                    watts += childWatt
                    power += ((ts - accumEnergyTotalTS) / 3600 * childWatt) / 1000
            self._addAccumEnergy(dev, power, ts)
            wattsStr = "%.2f W" % (watts)
            keyValueList.append(
                {'key': 'curEnergyLevel', 'value': watts, 'uiValue': wattsStr})
        dev.updateStatesOnServer(keyValueList)

    def _addAccumEnergy(self, dev, energy, ts, resetTS=True, resetWatt=False):
        keyValueList = []
        if "accumEnergyTotal" in dev.states:
            accumKwh = dev.states.get("accumEnergyTotal", 0) + energy
            accumKwhStr = "%.3f kWh" % (accumKwh)
            keyValueList.append(
                {'key': 'accumEnergyTotal', 'value': accumKwh, 'uiValue': accumKwhStr})
            if resetTS:
                keyValueList.append(
                    {'key': 'accumEnergyTotalTS', 'value': ts, 'uiValue': "%d" % ts})
            if resetWatt:
                keyValueList.append(
                    {'key': 'curEnergyLevel', 'value': 0, 'uiValue': "0 Watt"})
            dev.updateStatesOnServer(keyValueList)

    def runConcurrentThread(self):
        try:
            ts = time.time()
            self.updater.checkForUpdate()
            while True:
                for dev in indigo.devices.iter("self"):
                    if not dev.enabled or not dev.configured:
                        continue
                    self._refreshState(dev)

                if time.time()-ts > 3600*12:
                    self.updater.checkForUpdate()
                    ts = time.time()
                self.sleep(self.pluginPrefs.get("deviceUpdate", 300))
        except self.StopThread:
            pass  # Optionally catch the StopThread exception and do any needed cleanup.

    def logWatchedDevices(self):
        for devId in self.parentDevIdsWeUseDict:
            indigo.server.log(u"%s(%d)" % (indigo.devices[devId].name, devId))

    ########################################
    # Device Creation Callbacks
    ######################
    def getDeviceList(self, filter="supportsOnState", valuesDict=None, typeId="", targetId=0):
        # A little bit of Python list comprehension magic here. Basically, it iterates through
        # the device list and only adds the device if it has the filter property and is enabled.
        return [(dev.id, dev.name) for dev in indigo.devices if hasattr(dev, filter)]

    def devicesThatSupportOnState(self, filter="", valuesDict=None, typeId="", targetId=0):
        menuItems = []
        for dev in indigo.devices.iter("indigo.relay, indigo.dimmer"):
            menuItems.append((dev.id, dev.name))
        for dev in indigo.devices.iter("indigo.sensor, props.SupportsOnState"):
            menuItems.append((dev.id, dev.name))
        return menuItems

    def parentDeviceIdChanged(self, valuesDict, typeId, devId):
        if typeId == u"virtualDeviceEnergyMeter":
            dev = indigo.devices[int(valuesDict[u"parentDeviceId"])]
            if u"brightnessLevel" in dev.states:
                valuesDict[u"parentDeviceDimmer"] = True
            else:
                valuesDict[u"parentDeviceDimmer"] = False
        return valuesDict

    ########################################
    # Device Com
    ######################
    def deviceStartComm(self, dev):
        if dev.deviceTypeId == u"virtualDeviceEnergyMeter":
            if int(dev.ownerProps[u"parentDeviceId"]) not in indigo.devices:
                self.logger.warn(u"Parent device does not exits any more for device %s" % dev.name)
            else:
                self.parentDevIdsWeUseDict.append(int(dev.ownerProps[u"parentDeviceId"]))
        elif dev.deviceTypeId == u"virtualGroupEnergyMeter":
            for devId in dev.ownerProps[u"childEnergyMeters"]:
                if int(devId) not in indigo.devices:
                    self.logger.warn(u"Child device %s does not exits any more for device %s" % (devId, dev.name))
                else:
                    self.parentDevIdsWeUseDict.append(int(devId))
        self._refreshState(dev)

    def deviceStopComm(self, dev):
        if dev.deviceTypeId == u"virtualDeviceEnergyMeter":
            if int(dev.ownerProps[u"parentDeviceId"]) not in indigo.devices:
                self.logger.warn(u"Parent device does not exits any more for device %s" % dev.name)
            else:
                self.parentDevIdsWeUseDict.remove(int(dev.ownerProps[u"parentDeviceId"]))
        elif dev.deviceTypeId == u"virtualGroupEnergyMeter":
            for devId in dev.ownerProps[u"childEnergyMeters"]:
                if int(devId) not in indigo.devices:
                    self.logger.warn(u"Child device %s does not exits any more for device %s" % (devId, dev.name))
                else:
                    self.parentDevIdsWeUseDict.remove(int(devId))
        self._refreshState(dev)

    ########################################
    # Validation
    ######################
    def validateDeviceConfigUi(self, valuesDict, typeId, devId):
        errorDict = indigo.Dict()
        if typeId == u"virtualDeviceEnergyMeter":
            for value in valuesDict:
                if valuesDict['parentDeviceDimmer']:
                    fieldsToValidate = [u"powerAt1", u"powerAt33", u"powerAt66", u"powerAt100"]
                else:
                    fieldsToValidate = [u"powerAtOn"]
                if value in fieldsToValidate:
                    try:
                        valuesDict[value] = float(valuesDict[value])
                    except ValueError:
                        errorDict[value] = "The value of this field must be a number"
                        valuesDict[value] = 0
                elif value == u"parentDeviceId":
                        valuesDict[value] = int(valuesDict[value])
        if errorDict:
            return (False, valuesDict, errorDict)
        else:
            return (True, valuesDict)

    def validatePrefsConfigUi(self, valuesDict):
        errorDict = indigo.Dict()
        if valuesDict["deviceUpdate"] <= 0:
            errorDict["deviceUpdate"] = "The value of this field must be an integer"
            valuesDict["deviceUpdate"] = 300
        if errorDict:
            return (False, valuesDict, errorDict)
        else:
            return (True, valuesDict)

    ########################################
    # Methods for changes in Device states
    ########################################
    def deviceDeleted(self, dev):
        self.logger.debug(u"Device %s deleted" % (dev.name))

        if dev.id in self.parentDevIdsWeUseDict:
            ts = time.time()
            deviceEnergyMeters = filter(
                lambda x: x.deviceTypeId == u"virtualDeviceEnergyMeter" and x.ownerProps[u"parentDeviceId"] == str(
                    dev.id), indigo.devices.iter("self"))
            for deviceEnergyMeter in deviceEnergyMeters:
                self.logger.warn(u"Parent device %s has been deleted, "
                                 u"you must update Virtual Energy Device %s or deleted it."
                                 % (dev.name, deviceEnergyMeter.name))
                if dev.states['onOffState']:
                    self.logger.debug(u"Parent device %s is turned on" % (dev.name))
                    if u"brightnessLevel" in dev.states:
                        self.logger.debug(u"Parent device %s is a dimmer" % (dev.name))
                        watts = self.getCurPower(deviceEnergyMeter, int(dev.states.get("brightnessLevel")))
                    else:
                        self.logger.debug(u"Parent device %s is not a dimmer" % (dev.name))
                        watts = float(deviceEnergyMeter.ownerProps[u"powerAtOn"])
                    accumEnergyTotalTS = deviceEnergyMeter.states.get("accumEnergyTotalTS", ts)
                    energy = ((ts - accumEnergyTotalTS) / 3600 * watts) / 1000
                else:
                    energy = 0

                self._addAccumEnergy(deviceEnergyMeter, energy, ts, True, True)

            groupEnergyMeters = filter(
                lambda x: x.deviceTypeId == u"virtualGroupEnergyMeter" and str(
                dev.id) in x.ownerProps[u"childEnergyMeters"], indigo.devices.iter("self"))

            for groupEnergyMeter in groupEnergyMeters:
                self.logger.warn(u"Child device %s has been deleted, "
                                 u"it has been removed from Virtual Group Energy Meter %s"
                                 % (dev.name, groupEnergyMeter.name))
                accumEnergyTotalTS = groupEnergyMeter.states.get("accumEnergyTotalTS", ts)
                power = 0.0
                for devId in groupEnergyMeter.ownerProps[u"childEnergyMeters"]:
                    if devId == str(dev.id):
                        watt = dev.states.get('curEnergyLevel', 0)
                        power = ((ts - accumEnergyTotalTS) / 3600 * watt) / 1000
                    else:
                        childWatt = indigo.devices[int(devId)].states.get('curEnergyLevel', 0)
                        power += ((ts - accumEnergyTotalTS) / 3600 * childWatt) / 1000
                self._addAccumEnergy(dev, power, ts, True, True)

                groupEnergyMeter.ownerProps[u"childEnergyMeters"].remove(str(dev.id))
            self.parentDevIdsWeUseDict = filter(lambda a: a != dev.id, self.parentDevIdsWeUseDict)

        indigo.PluginBase.deviceDeleted(self, dev)  # be sure and call parent function

    def deviceUpdated(self, origDev, newDev):
        ts = time.time()
        if newDev.deviceTypeId == u"virtualDeviceEnergyMeter" or newDev.deviceTypeId == u"virtualGroupEnergyMeter":
            self.logger.debug(u"Device %s has change" % (newDev.name))
            if origDev.configured != newDev.configured:
                self.logger.debug(u"Device %s is configured" % (newDev.name))
                self.deviceStartComm(newDev)
            elif origDev.enabled != newDev.enabled:
                if newDev.enabled:
                    self.logger.debug(u"Device %s is is enabled" % (newDev.name))
                    self.deviceStartComm(origDev)
                else:
                    self.logger.debug(u"Device %s is is disabled" % (newDev.name))
                    self.deviceStopComm(origDev)
            elif newDev.deviceTypeId == u"virtualDeviceEnergyMeter"\
                    and 'parentDeviceId' in origDev.ownerProps\
                    and origDev.ownerProps['parentDeviceId'] != newDev.ownerProps['parentDeviceId']\
                    and int(origDev.ownerProps[u"parentDeviceId"]) in indigo.devices:
                parentDevice = indigo.devices[int(origDev.ownerProps[u"parentDeviceId"])]
                self.logger.debug(u"Device %s has changed parent device to %s" % (newDev.name, parentDevice.name))
                if origDev.ownerProps[u"parentDeviceId"] in self.parentDevIdsWeUseDict:
                    self.parentDevIdsWeUseDict.remove(int(origDev.ownerProps[u"parentDeviceId"]))
                self.parentDevIdsWeUseDict.append(int(newDev.ownerProps[u"parentDeviceId"]))
                if parentDevice.states['onOffState']:
                    self.logger.debug(u"Parent device %s is turned on" % (parentDevice.name))
                    if u"brightnessLevel" in parentDevice.states:
                        self.logger.debug(u"Parent device %s is a dimmer" % (parentDevice.name))
                        watts = self.getCurPower(origDev, int(parentDevice.states.get("brightnessLevel")))
                    else:
                        self.logger.debug(u"Parent device %s is not a dimmer" % (parentDevice.name))
                        watts = float(origDev.ownerProps[u"powerAtOn"])
                    accumEnergyTotalTS = origDev.states.get("accumEnergyTotalTS", ts)
                    energy = ((ts - accumEnergyTotalTS) / 3600 * watts) / 1000
                else:
                    energy = 0

                self._addAccumEnergy(newDev, energy, ts)
                self._refreshState(newDev)

            elif newDev.deviceTypeId == u"virtualGroupEnergyMeter" \
                    and origDev.ownerProps['childEnergyMeters'] != newDev.ownerProps['childEnergyMeters']:
                self._refreshState(newDev)

        if newDev.id not in self.parentDevIdsWeUseDict:
            return
        else:
                self.logger.debug(u"Device %s has change" % (newDev.name))
        if (u"onOffState" in origDev.states and origDev.states['onOffState'] != newDev.states['onOffState'])\
                or (u"brightnessLevel" in origDev.states
                    and origDev.states['brightnessLevel'] != newDev.states['brightnessLevel']):
            self.logger.debug(U"The parent device, %s, has changed onOff state or brightness level" % origDev.name)
            #TODO: Fix error handling if dev don't exists
            self.logger.debug(U"Getting all Virtual Energy Meters with parent device: %s" % origDev.name)
            devs = filter(lambda x: x.deviceTypeId == u"virtualDeviceEnergyMeter" and x.ownerProps[u"parentDeviceId"] == str(origDev.id), indigo.devices.iter("self"))
            self.logger.debug(U"Found %d Virtual Energy Meters with parent device: %s" % (len(devs), origDev.name))
            for dev in devs:
                self.logger.debug(U"Syncing Virtual Energy Meter %s with %s" % (dev.name, origDev.name))
                if origDev.states['onOffState']:
                    if u"brightnessLevel" in origDev.states:
                        watts = self.getCurPower(dev, int(origDev.states.get("brightnessLevel")))
                    else:
                        watts = float(dev.ownerProps[u"powerAtOn"])
                    accumEnergyTotalTS = dev.states.get("accumEnergyTotalTS", ts)
                    energy = ((ts - accumEnergyTotalTS) / 3600 * watts) / 1000
                else:
                    energy = 0
                self._addAccumEnergy(dev, energy, ts)
                self._refreshState(dev)
        if (u"curEnergyLevel" in origDev.states and origDev.states['curEnergyLevel'] != newDev.states['curEnergyLevel']):
            # or (u"accumEnergyTotal" in origDev.states and origDev.states['accumEnergyTotal'] != newDev.states['accumEnergyTotal']) \
            self.logger.debug(U"Device, %s has changed curEnergyLevel" % origDev.name)
            devs = filter(lambda x: x.deviceTypeId == u"virtualGroupEnergyMeter" and str(origDev.id) in x.ownerProps[u"childEnergyMeters"], indigo.devices.iter("self"))
            self.logger.debug(U"Found %d Virtual Group Energy Meters with child device: %s" % (len(devs), origDev.name))
            for dev in devs:
                self.logger.debug(u"Device %s has change, update Group Energy Meter %s" % (origDev.name, dev.name))
                ts = time.time()
                accumEnergyTotalTS = dev.states.get("accumEnergyTotalTS", ts)
                power = 0.0
                for devId in dev.ownerProps[u"childEnergyMeters"]:
                    if devId == str(origDev.id):
                        watt = origDev.states.get('curEnergyLevel', 0)
                        power = ((ts - accumEnergyTotalTS) / 3600 * watt) / 1000
                    else:
                        childWatt = indigo.devices[int(devId)].states.get('curEnergyLevel', 0)
                        power += ((ts - accumEnergyTotalTS) / 3600 * childWatt) / 1000
                self._addAccumEnergy(dev, power, ts)
                self._refreshState(dev)

        indigo.PluginBase.deviceUpdated(self, origDev, newDev)  # be sure and call parent function

    def getCurPower(self, dev, dimLevel):
        xp = [1, 33, 66, 100]
        fp = [float(dev.ownerProps[u"powerAt1"]),
              float(dev.ownerProps[u"powerAt33"]),
              float(dev.ownerProps[u"powerAt66"]),
              float(dev.ownerProps[u"powerAt100"])]
        return np.interp(dimLevel, xp, fp)

    ########################################
    # General Action callback
    ######################
    def actionControlGeneral(self, action, dev):
        ###### BEEP ######
        if action.deviceAction == indigo.kDeviceGeneralAction.Beep:
            # Beep the hardware module (dev) here:
            # ** IMPLEMENT ME **
            indigo.server.log(u"sent \"%s\" %s" % (dev.name, "beep request"))

        ###### ENERGY UPDATE ######
        elif action.deviceAction == indigo.kDeviceGeneralAction.EnergyUpdate:
            # Request hardware module (dev) for its most recent meter data here:
            # ** IMPLEMENT ME **
            self._refreshState(dev, True)

        ###### ENERGY RESET ######
        elif action.deviceAction == indigo.kDeviceGeneralAction.EnergyReset:
            # Request that the hardware module (dev) reset its accumulative energy usage data here:
            # ** IMPLEMENT ME **
            indigo.server.log(u"sent \"%s\" %s" % (dev.name, "energy usage reset"))
            # And then tell Indigo to reset it by just setting the value to 0.
            # This will automatically reset Indigo's time stamp for the accumulation.
            dev.updateStateOnServer("accumEnergyTotal", 0.0)

        ###### STATUS REQUEST ######
        elif action.deviceAction == indigo.kDeviceGeneralAction.RequestStatus:
            # Query hardware module (dev) for its current status here:
            # ** IMPLEMENT ME **
            self._refreshState(dev, True)

    ########################################
    # Custom Plugin Action callbacks (defined in Actions.xml)
    ######################
    def setBacklightBrightness(self, pluginAction, dev):
        try:
            newBrightness = int(pluginAction.props.get(u"brightness", 100))
        except ValueError:
            # The int() cast above might fail if the user didn't enter a number:
            indigo.server.log(
                u"set backlight brightness action to device \"%s\" -- invalid brightness value" % (dev.name,),
                isError=True)
            return

        # Command hardware module (dev) to set backlight brightness here:
        # ** IMPLEMENT ME **
        sendSuccess = True  # Set to False if it failed.

        if sendSuccess:
            # If success then log that the command was successfully sent.
            indigo.server.log(u"sent \"%s\" %s to %d" % (dev.name, "set backlight brightness", newBrightness))

            # And then tell the Indigo Server to update the state:
            dev.updateStateOnServer("backlightBrightness", newBrightness)
        else:
            # Else log failure but do NOT update state on Indigo Server.
            indigo.server.log(u"send \"%s\" %s to %d failed" % (dev.name, "set backlight brightness", newBrightness),
                              isError=True)

    ########################################
    # Sensor Action callback
    ######################
    def actionControlSensor(self, action, dev):
        ###### TURN ON ######
        # Ignore turn on/off/toggle requests from clients since this is a read-only sensor.
        if action.sensorAction == indigo.kSensorAction.TurnOn:
            indigo.server.log(u"ignored \"%s\" %s request (sensor is read-only)" % (dev.name, "on"))
        # But we could request a sensor state update if we wanted like this:
        # dev.updateStateOnServer("onOffState", True)

        ###### TURN OFF ######
        # Ignore turn on/off/toggle requests from clients since this is a read-only sensor.
        elif action.sensorAction == indigo.kSensorAction.TurnOff:
            indigo.server.log(u"ignored \"%s\" %s request (sensor is read-only)" % (dev.name, "off"))
        # But we could request a sensor state update if we wanted like this:
        # dev.updateStateOnServer("onOffState", False)

        ###### TOGGLE ######
        # Ignore turn on/off/toggle requests from clients since this is a read-only sensor.
        elif action.sensorAction == indigo.kSensorAction.Toggle:
            indigo.server.log(u"ignored \"%s\" %s request (sensor is read-only)" % (dev.name, "toggle"))
            # But we could request a sensor state update if we wanted like this:
            # dev.updateStateOnServer("onOffState", not dev.onState)

    ########################################
    # Relay / Dimmer Action callback
    ######################
    def actionControlDimmerRelay(self, action, dev):
        ###### TURN ON ######
        if action.deviceAction == indigo.kDimmerRelayAction.TurnOn:
            # Command hardware module (dev) to turn ON here:
            # ** IMPLEMENT ME **
            sendSuccess = True  # Set to False if it failed.

            if sendSuccess:
                # If success then log that the command was successfully sent.
                indigo.server.log(u"sent \"%s\" %s" % (dev.name, "on"))

                # And then tell the Indigo Server to update the state.
                dev.updateStateOnServer("onOffState", True)
            else:
                # Else log failure but do NOT update state on Indigo Server.
                indigo.server.log(u"send \"%s\" %s failed" % (dev.name, "on"), isError=True)

        ###### TURN OFF ######
        elif action.deviceAction == indigo.kDimmerRelayAction.TurnOff:
            # Command hardware module (dev) to turn OFF here:
            # ** IMPLEMENT ME **
            sendSuccess = True  # Set to False if it failed.

            if sendSuccess:
                # If success then log that the command was successfully sent.
                indigo.server.log(u"sent \"%s\" %s" % (dev.name, "off"))

                # And then tell the Indigo Server to update the state:
                dev.updateStateOnServer("onOffState", False)
            else:
                # Else log failure but do NOT update state on Indigo Server.
                indigo.server.log(u"send \"%s\" %s failed" % (dev.name, "off"), isError=True)

        ###### TOGGLE ######
        elif action.deviceAction == indigo.kDimmerRelayAction.Toggle:
            # Command hardware module (dev) to toggle here:
            # ** IMPLEMENT ME **
            newOnState = not dev.onState
            sendSuccess = True  # Set to False if it failed.

            if sendSuccess:
                # If success then log that the command was successfully sent.
                indigo.server.log(u"sent \"%s\" %s" % (dev.name, "toggle"))

                # And then tell the Indigo Server to update the state:
                dev.updateStateOnServer("onOffState", newOnState)
            else:
                # Else log failure but do NOT update state on Indigo Server.
                indigo.server.log(u"send \"%s\" %s failed" % (dev.name, "toggle"), isError=True)

        ###### SET BRIGHTNESS ######
        elif action.deviceAction == indigo.kDimmerRelayAction.SetBrightness:
            # Command hardware module (dev) to set brightness here:
            # ** IMPLEMENT ME **
            newBrightness = action.actionValue
            sendSuccess = True  # Set to False if it failed.

            if sendSuccess:
                # If success then log that the command was successfully sent.
                indigo.server.log(u"sent \"%s\" %s to %d" % (dev.name, "set brightness", newBrightness))

                # And then tell the Indigo Server to update the state:
                dev.updateStateOnServer("brightnessLevel", newBrightness)
            else:
                # Else log failure but do NOT update state on Indigo Server.
                indigo.server.log(u"send \"%s\" %s to %d failed" % (dev.name, "set brightness", newBrightness),
                                  isError=True)

        ###### BRIGHTEN BY ######
        elif action.deviceAction == indigo.kDimmerRelayAction.BrightenBy:
            # Command hardware module (dev) to do a relative brighten here:
            # ** IMPLEMENT ME **
            newBrightness = dev.brightness + action.actionValue
            if newBrightness > 100:
                newBrightness = 100
            sendSuccess = True  # Set to False if it failed.

            if sendSuccess:
                # If success then log that the command was successfully sent.
                indigo.server.log(u"sent \"%s\" %s to %d" % (dev.name, "brighten", newBrightness))

                # And then tell the Indigo Server to update the state:
                dev.updateStateOnServer("brightnessLevel", newBrightness)
            else:
                # Else log failure but do NOT update state on Indigo Server.
                indigo.server.log(u"send \"%s\" %s to %d failed" % (dev.name, "brighten", newBrightness), isError=True)

        ###### DIM BY ######
        elif action.deviceAction == indigo.kDimmerRelayAction.DimBy:
            # Command hardware module (dev) to do a relative dim here:
            # ** IMPLEMENT ME **
            newBrightness = dev.brightness - action.actionValue
            if newBrightness < 0:
                newBrightness = 0
            sendSuccess = True  # Set to False if it failed.

            if sendSuccess:
                # If success then log that the command was successfully sent.
                indigo.server.log(u"sent \"%s\" %s to %d" % (dev.name, "dim", newBrightness))

                # And then tell the Indigo Server to update the state:
                dev.updateStateOnServer("brightnessLevel", newBrightness)
            else:
                # Else log failure but do NOT update state on Indigo Server.
                indigo.server.log(u"send \"%s\" %s to %d failed" % (dev.name, "dim", newBrightness), isError=True)

        ###### SET COLOR LEVELS ######
        elif action.deviceAction == indigo.kDimmerRelayAction.SetColorLevels:
            # action.actionValue is a dict containing the color channel key/value
            # pairs. All color channel keys (redLevel, greenLevel, etc.) are optional
            # so plugin should handle cases where some color values are not specified
            # in the action.
            actionColorVals = action.actionValue

            # Construct a list of channel keys that are possible for what this device
            # supports. It may not support RGB or may not support white levels, for
            # example, depending on how the device's properties (SupportsColor, SupportsRGB,
            # SupportsWhite, SupportsTwoWhiteLevels, SupportsWhiteTemperature) have
            # been specified.
            channelKeys = []
            usingWhiteChannels = False
            if dev.supportsRGB:
                channelKeys.extend(['redLevel', 'greenLevel', 'blueLevel'])
            if dev.supportsWhite:
                channelKeys.extend(['whiteLevel'])
                usingWhiteChannels = True
            if dev.supportsTwoWhiteLevels:
                channelKeys.extend(['whiteLevel2'])
            elif dev.supportsWhiteTemperature:
                channelKeys.extend(['whiteTemperature'])
            # Note having 2 white levels (cold and warm) takes precedence over
            # the user of a white temperature value. You cannot have both although
            # you can have a single white level and a white temperature value.

            # Next enumerate through the possible color channels and extract that
            # value from the actionValue (actionColorVals).
            keyValueList = []
            resultVals = []
            for channel in channelKeys:
                if channel in actionColorVals:
                    brightness = float(actionColorVals[channel])
                    brightnessByte = int(round(255.0 * (brightness / 100.0)))

                    # Command hardware module (dev) to change its color level here:
                    # ** IMPLEMENT ME **

                    if channel in dev.states:
                        keyValueList.append({'key': channel, 'value': brightness})
                    result = str(int(round(brightness)))
                elif channel in dev.states:
                    # If the action doesn't specify a level that is needed (say the
                    # hardware API requires a full RGB triplet to be specified, but
                    # the action only contains green level), then the plugin could
                    # extract the currently cached red and blue values from the
                    # dev.states[] dictionary:
                    cachedBrightness = float(dev.states[channel])
                    cachedBrightnessByte = int(round(255.0 * (cachedBrightness / 100.0)))
                    # Could show in the Event Log either '--' to indicate this level wasn't
                    # passed in by the action:
                    result = '--'
                # Or could show the current device state's cached level:
                #	result = str(int(round(cachedBrightness)))

                # Add a comma to separate the RGB values from the white values for logging.
                if channel == 'blueLevel' and usingWhiteChannels:
                    result += ","
                elif channel == 'whiteTemperature' and result != '--':
                    result += " K"
                resultVals.append(result)
            # Set to False if it failed.
            sendSuccess = True

            resultValsStr = ' '.join(resultVals)
            if sendSuccess:
                # If success then log that the command was successfully sent.
                indigo.server.log(u"sent \"%s\" %s to %s" % (dev.name, "set color", resultValsStr))

                # And then tell the Indigo Server to update the color level states:
                if len(keyValueList) > 0:
                    dev.updateStatesOnServer(keyValueList)
            else:
                # Else log failure but do NOT update state on Indigo Server.
                indigo.server.log(u"send \"%s\" %s to %s failed" % (dev.name, "set color", resultValsStr), isError=True)

    ########################################
    # Plugin Config callback
    ######################
    def closedPrefsConfigUi(self, valuesDict, userCancelled):
        if (not userCancelled):
            self.setLogLevel()

    def loggingLevelList(self, filter="", valuesDict=None, typeId="", targetId=0):
        logLevels = [
            [logging.DEBUG, "Debug"],
            (logging.INFO, "Normal"),
            (logging.WARN, "Warning"),
            (logging.ERROR, "Error"),
            (logging.CRITICAL, "Critical")
        ]
        return logLevels

    def setLogLevel(self):
        logLevel = self.pluginPrefs.get("loggingLevel", logging.INFO)
        if type(logLevel) is not int:
            logLevel = int(logLevel)
        self.logger.setLevel(logLevel)
        self.debug = (self.logger.level <= logging.DEBUG)
        indigo.server.log(
            u"Setting logging level to %s" % (self.loggingLevelList()[int(self.pluginPrefs["loggingLevel"]) / 10 - 1][1]))


    ########################################
    # Plugin GitHub Updater
    ######################
    def updatePlugin(self):
        self.updater.update()

    def checkForUpdates(self):
        self.updater.checkForUpdate()

